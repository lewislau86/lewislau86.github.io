// 故意编译失败，用于第 12 章练习；不属于 Cargo 的编译目标。
fn main() {
    let key = String::from("course");
    let _owned = key;
    println!("{key}");
}
