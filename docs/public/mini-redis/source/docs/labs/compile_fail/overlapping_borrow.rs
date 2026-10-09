// 故意编译失败：共享引用后面仍被使用，不能中途独占修改。
fn main() {
    let mut value = String::from("rust");
    let reader = &value;
    let writer = &mut value;
    writer.push('!');
    println!("{reader}");
}
