trait Area {
    fn area(&self) -> f32;
}

struct Rect {
    width: f32,
    height: f32,
}

impl Area for Rect {
    fn area(&self) -> f32 {
        self.width * self.height
    }
}

fn take_ownership(text: String) -> usize {
    text.len()
}

fn main() {
    // 移动：y 接收 Vec 的所有权，x 不能再使用。
    let x = vec![1, 2, 3];
    let y = x;
    let z = y.clone();
    assert_eq!(y.len(), 3);
    assert_eq!(z.len(), 3);

    // 按值传参会移交 String；函数返回后原变量不能再用。
    let text = String::from("burn");
    let len = take_ownership(text);
    assert_eq!(len, 4);

    // trait 只要求“能做 area”，不要求具体类型。
    let rect = Rect { width: 2.0, height: 3.0 };
    assert_eq!(rect.area(), 6.0);
    println!("rect area = {}", rect.area());

    // Option 表示可能没有；Result 表示可能失败；? 把错误交给调用者。
    let maybe: Option<i32> = Some(7);
    assert_eq!(maybe.map(|v| v * 2), Some(14));
    let parsed: Result<i32, _> = "42".parse::<i32>();
    assert_eq!(parsed.unwrap(), 42);

    println!("moved Vec clone length = {}", z.len());
    println!("String length = {}", len);
    println!("Option = {:?}, parsed = 42", maybe);
}
