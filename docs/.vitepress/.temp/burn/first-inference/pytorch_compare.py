"""与 Burn comparison.rs 对照；只用 CPU，不需要数据集或额外下载。"""

import torch


def close(actual, expected):
    torch.testing.assert_close(
        actual, torch.tensor(expected, dtype=actual.dtype), rtol=1e-5, atol=1e-5
    )


def main():
    print(f"PyTorch {torch.__version__}; CPU")
    x = torch.tensor([[1.0, 2.0]], requires_grad=True)
    w = torch.tensor([[1.0, -1.0], [2.0, 1.0]], requires_grad=True)
    b = torch.tensor([[0.0, 1.0]], requires_grad=True)
    h = torch.relu(x @ w + b)
    assert tuple(h.shape) == (1, 2)
    close(h, [[5.0, 2.0]])
    h.sum().backward()
    close(x.grad, [[0.0, 3.0]])
    close(w.grad, [[1.0, 1.0], [2.0, 2.0]])
    close(b.grad, [[1.0, 1.0]])
    print(f"H = {h.detach().tolist()}; shape = {list(h.shape)}")
    print(f"dX = {x.grad.tolist()}; dW = {w.grad.tolist()}; db = {b.grad.tolist()}")

    # Linear 保存 [out_features, in_features]，因此写入主线 W 的转置。
    linear = torch.nn.Linear(2, 2)
    with torch.no_grad():
        linear.weight.copy_(w.detach().T)
        linear.bias.copy_(b.detach().reshape(2))
    linear.eval()
    with torch.no_grad():
        close(torch.relu(linear(x.detach())), [[5.0, 2.0]])
    print("nn.Linear with transposed weight: PASS")

    x = torch.tensor([-2.0, 0.0, 3.0], requires_grad=True)
    g = torch.tensor([2.0, -1.0, 0.5])
    ((x * x + x) * g).sum().backward()
    close(x.grad, [-6.0, -1.0, 3.5])
    print(f"weighted dX = {x.grad.tolist()}")

    w = torch.tensor([0.0], requires_grad=True)
    loss = ((w * 2.0 - 4.0) ** 2).sum()
    close(loss.reshape(1), [16.0])
    loss.backward()
    close(w.grad, [-16.0])
    with torch.no_grad():
        updated = w - 0.1 * w.grad
        new_loss = ((updated * 2.0 - 4.0) ** 2).sum()
    close(updated, [1.6])
    close(new_loss.reshape(1), [0.64])
    print(f"SGD w = {updated.tolist()}; loss after = {new_loss.item():.6f}")


if __name__ == "__main__":
    main()
