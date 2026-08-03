# 用户输入目录

把用户自己准备的请求 JSON 和输入 provenance manifest 放在这里，例如：

```text
inputs/
├── visible-light-review.json
└── visible-light-inputs.json
```

论文 PDF、SI、Generic Parse 输出和 Chemical ZIP 可以放在仓库外部；路径写入 JSON
后，命令会按 hash 读取并绑定。真实输入文件不会被 Git 提交。
