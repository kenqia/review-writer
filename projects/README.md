# 用户项目目录

这个目录是 review-writer v0.1 的默认本地工作区。用户可以把自己创建的综述项目放在这里，
例如：

```text
projects/
└── visible-light-review/
```

运行命令时使用：

```bash
python scripts/run_vertical_review.py bootstrap-corpus \
  --review-root projects \
  --request inputs/visible-light-review.json
```

实际项目、论文 PDF、SI、Generic Parse 和 Chemical ZIP 会被 Git 忽略，不会进入提交。
这个目录只负责保存本地运行数据；用户说明仍以仓库根目录的中文文档为准。
