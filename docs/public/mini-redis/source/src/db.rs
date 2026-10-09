use tokio::sync::{broadcast, Notify};
use tokio::time::{self, Duration, Instant};

use bytes::Bytes;
use std::collections::{BTreeSet, HashMap};
use std::sync::{Arc, Mutex};
use tracing::debug;

/// 服务持有的数据库清理守卫；Drop 时设置停止标记并唤醒过期任务。
/// 这是 RAII：资源释放触发收尾动作，但通知退出不等于已经 join 后台任务。
#[derive(Debug)]
pub(crate) struct DbDropGuard {
    /// 守卫持有一个 Db 句柄；销毁守卫时通知后台清理停止。
    db: Db,
}

/// 所有连接共享的数据库句柄。
///
/// Arc 指向同一份主表、频道表与过期索引；克隆 Db 只增加引用计数，不复制键值。
/// Db::new 启动清理任务，任务也持有 Arc，因此停机由 DbDropGuard 显式通知，
/// 不是等待所有 Db 自动消失。
#[derive(Debug, Clone)]
pub(crate) struct Db {
    /// 原子引用计数的共享所有权；Arc 只管理存活时间，数据修改仍依赖 Mutex。
    shared: Arc<Shared>,
}

#[derive(Debug)]
struct Shared {
    /// 标准库互斥锁保护 State，锁内没有 await。
    ///
    /// 短同步临界区可以使用 std::sync::Mutex，但竞争仍会阻塞线程。
    /// 需要跨 await 持锁时应重新评估设计或异步锁；长耗时阻塞工作需考虑 spawn_blocking。
    state: Mutex<State>,

    /// 唤醒清理任务重新检查索引或停止标记；Notify 不携带哪一个 key 的消息。
    background_task: Notify,
}

#[derive(Debug)]
struct State {
    /// 主键值表，拥有键 String 与 Entry。
    entries: HashMap<String, Entry>,

    /// 独立频道表；同名频道和键互不覆盖。取消订阅不会自动移除此表中的 Sender。
    pub_sub: HashMap<String, broadcast::Sender<Bytes>>,

    /// 按 (到期时刻, 键名) 的字典序排序。
    /// 同一时刻可有多个键，加入键名防止 BTreeSet 把它们视为同一元素。
    expirations: BTreeSet<(Instant, String)>,

    /// DbDropGuard 析构时置 true，清理任务在醒来后检查并退出。
    shutdown: bool,
}

/// 主表中的一条记录，值与可选到期时刻一起保存。
#[derive(Debug)]
struct Entry {
    /// Bytes 克隆共享底层内容，避免读取响应时复制整个值。
    data: Bytes,

    /// Some(Instant) 表示到期时刻；None 表示无 TTL，不等于立即过期。
    expires_at: Option<Instant>,
}

impl DbDropGuard {
    /// 创建 Db 与清理守卫；Drop 将触发停止通知。
    pub(crate) fn new() -> DbDropGuard {
        DbDropGuard { db: Db::new() }
    }

    /// 返回 Db 克隆句柄；调用者拥有自己的 Arc 引用，访问的仍是同一份状态。
    pub(crate) fn db(&self) -> Db {
        self.db.clone()
    }
}

impl Drop for DbDropGuard {
    fn drop(&mut self) {
        // Drop 只能同步通知；此处不能 await 后台任务完成。
        self.db.shutdown_purge_task();
    }
}

impl Db {
    /// 建立空表和 Notify，并把共享状态的一个 Arc 克隆交给后台任务。
    pub(crate) fn new() -> Db {
        let shared = Arc::new(Shared {
            state: Mutex::new(State {
                entries: HashMap::new(),
                pub_sub: HashMap::new(),
                expirations: BTreeSet::new(),
                shutdown: false,
            }),
            background_task: Notify::new(),
        });

        // spawn 提交独立任务；clone 保留前台句柄，不把唯一 Arc 全部移走。
        tokio::spawn(purge_expired_tasks(shared.clone()));

        Db { shared }
    }

    /// 读取键对应的数据；主表无记录返回 None。
    /// 当前不检查 expires_at，因此清理任务尚未运行时可能读到已经到期的旧值。
    pub(crate) fn get(&self, key: &str) -> Option<Bytes> {
        // lock 返回 MutexGuard，离开作用域时自动解锁；unwrap 在锁中毒时会 panic。
        // 返回 Bytes 克隆使后续网络写不必继续持锁。
        let state = self.shared.state.lock().unwrap();
        state.entries.get(key).map(|entry| entry.data.clone())
    }

    /// 接管 key/value 并覆盖旧值，同时维护可选过期索引。
    /// 这是同步操作，返回时共享状态已改变；之后发送 OK 失败不会回滚写入。
    pub(crate) fn set(&self, key: String, value: Bytes, expire: Option<Duration>) {
        let mut state = self.shared.state.lock().unwrap();

        // 先判断是否需要重排后台等待；只有新期限比当前最早期限更早时才需要唤醒。
        let mut notify = false;

        let expires_at = expire.map(|duration| {
            // Option::map 只在 Some(duration) 时运行闭包，将相对时长转为绝对时刻。
            let when = Instant::now() + duration;

            // 若没有旧期限，unwrap_or(true) 表示需要唤醒原本只等 Notify 的任务。
            notify = state
                .next_expiration()
                .map(|expiration| expiration > when)
                .unwrap_or(true);

            when
        });

        // insert 返回被替换的旧 Entry，供下面撤销旧过期索引。
        let prev = state.entries.insert(
            key.clone(),
            Entry {
                data: value,
                expires_at,
            },
        );

        // 即使这次不带 TTL，也要撤销被覆盖记录的旧期限。
        if let Some(prev) = prev {
            if let Some(when) = prev.expires_at {
                // 移除旧 (时刻, 键) 元组，防止未来误删新值。
                state.expirations.remove(&(when, key.clone()));
            }
        }

        // 先删除旧索引，再插入新索引；相同元组若反过来操作，会误删刚插入的记录。
        if let Some(when) = expires_at {
            state.expirations.insert((when, key));
        }

        // 显式 drop MutexGuard 提前解锁，让被唤醒的任务可以立即竞争锁。
        drop(state);

        if notify {
            // Notify 只是提醒重新查看共享索引，不为每次 SET 创建一份清理任务。
            self.shared.background_task.notify_one();
        }
    }

    /// 取得频道 Receiver，后续由 Subscribe::apply 读取。
    /// Receiver 的所有权移动到频道流中，释放它会解除这份订阅。
    pub(crate) fn subscribe(&self, key: String) -> broadcast::Receiver<Bytes> {
        use std::collections::hash_map::Entry;

        // 修改频道表之前取得可变 Guard，确保查询/创建是一个临界区。
        let mut state = self.shared.state.lock().unwrap();

        // HashMap::entry 一次查询区分 Occupied/Vacant，避免先查后插的重复逻辑。
        match state.pub_sub.entry(key) {
            Entry::Occupied(e) => e.get().subscribe(),
            Entry::Vacant(e) => {
                // 创建容量 1024 的 broadcast。多个 Receiver 各自接收消息，消息可共享 Bytes。
                // 容量耗尽时旧消息被覆盖，落后的接收者收到 Lagged；这不是可靠持久化队列。
                let (tx, rx) = broadcast::channel(1024);
                e.insert(tx);
                rx
            }
        }
    }

    /// 向频道发送消息并返回当前接收者数量；该数量不代表业务消费确认。
    pub(crate) fn publish(&self, key: &str, value: Bytes) -> usize {
        let state = self.shared.state.lock().unwrap();

        state
            .pub_sub
            .get(key)
            // 有 Sender 时尝试 send；没有活接收者会失败，转成数量 0。
            .map(|tx| tx.send(value).unwrap_or(0))
            // 频道不存在时 Option 为 None，直接返回 0。
            .unwrap_or(0)
    }

    /// 由 DbDropGuard::drop 调用：设置停止标记并唤醒清理任务。
    fn shutdown_purge_task(&self) {
        // 先在锁内更新真实状态，再发通知；Notify 自身不保存 shutdown 布尔值。
        let mut state = self.shared.state.lock().unwrap();
        state.shutdown = true;

        // 先解锁再通知，降低唤醒后的无谓争锁。
        drop(state);
        self.shared.background_task.notify_one();
    }
}

impl Shared {
    /// 删除当前所有到期键，返回下一次到期时刻；None 表示当前无需定时等待。
    fn purge_expired_keys(&self) -> Option<Instant> {
        let mut state = self.state.lock().unwrap();

        if state.shutdown {
            // 停止标记已设置，不再处理索引；外层任务下一轮检查后退出。
            return None;
        }

        // lock 返回的是 Guard；&mut *state 经 DerefMut 得到 &mut State。
        // 显式借用结构体后，编译器可以区分 entries 与 expirations 两个互不重叠的字段。
        let state = &mut *state;

        // 固定本轮 now，删除所有到期时刻小于或等于 now 的项。
        let now = Instant::now();

        while let Some(&(when, ref key)) = state.expirations.iter().next() {
            if when > now {
                // 遇到未来期限就停止；BTreeSet 保证后续项不会更早到期。
                return Some(when);
            }

            // 同时删除主表和值对应的索引；两步仍处于同一锁保护下。
            state.entries.remove(key);
            state.expirations.remove(&(when, key.clone()));
        }

        None
    }

    /// 读取停止标记；它来自 DbDropGuard 的通知，与 Arc 引用数量不是同一条件。
    fn is_shutdown(&self) -> bool {
        self.state.lock().unwrap().shutdown
    }
}

impl State {
    fn next_expiration(&self) -> Option<Instant> {
        self.expirations
            .iter()
            .next()
            .map(|expiration| expiration.0)
    }
}

/// 后台过期循环：查看共享索引、等待时间或通知，直到观察到停止标记。
async fn purge_expired_tasks(shared: Arc<Shared>) {
    // 每轮重新查状态；被唤醒不一定意味着有键到期，也可能是停机。
    while !shared.is_shutdown() {
        // 同步清理后取得下一个期限，不能拿着 MutexGuard 跨 await 等待。
        if let Some(when) = shared.purge_expired_keys() {
            // select 同时轮询定时器与 Notify，任一完成就重读共享状态。
            // 被取消的是这次等待 Future，不会撤销已经完成的数据库更新。
            tokio::select! {
                _ = time::sleep_until(when) => {}
                _ = shared.background_task.notified() => {}
            }
        } else {
            // 没有期限时只等通知，避免空转；新 TTL 或停机会唤醒这里。
            shared.background_task.notified().await;
        }
    }

    debug!("Purge background task shut down")
}
