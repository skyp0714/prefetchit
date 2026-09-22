import torch, torchvision, time
torch.set_num_threads(1)
m = torchvision.models.resnet50(weights=None).eval()
x = torch.randn(1, 3, 224, 224)
with torch.no_grad():
    for _ in range(3): m(x)
    t0 = time.time(); n = 0
    while time.time() - t0 < 60:
        m(x); n += 1
print("inferences", n)
