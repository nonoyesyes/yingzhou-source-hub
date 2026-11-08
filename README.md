# yingzhou-source-hub
映舟源仓
映舟TV 的优选源配置仓库。仅收录用户自建、合法授权或公开可用的源配置，不提供任何影视内容。

## 增量读取

从 `delta/index.json` 获取基线及按序追加的不可变批次。`feed.json` 作为首次导入的固定基线保留，不再代表最新累计状态；新客户端首次导入后只读取后续批次。完整请求去重，新增出处、元数据修正和明确撤回通过更新操作交付，历史不因暂时抓取失败被删除。

接入约定、生成/验证命令与限制见 [delta/README.md](delta/README.md)。传输格式为 `source-hub-delta.v1`，还原后的业务数据仍为 `source-hub-feed.v1`。
