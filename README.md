# yingzhou-source-hub
映舟源仓
映舟TV 的优选源配置仓库。仅收录用户自建、合法授权或公开可用的源配置，不提供任何影视内容。

## 增量读取

从 `delta/index.json` 获取基线及按序追加的不可变批次。`feed.json` 作为首次导入的固定基线保留，不再代表最新累计状态；新客户端首次导入后只读取后续批次。完整请求去重，新增出处、元数据修正和明确撤回通过更新操作交付，历史不因暂时抓取失败被删除。

接入约定、生成/验证命令与限制见 [delta/README.md](delta/README.md)。传输格式为 `source-hub-delta.v1`，还原后的业务数据仍为 `source-hub-feed.v1`。

历史文档 [INCREMENTAL_FETCH.md](archive/reference/INCREMENTAL_FETCH.md) 是固定基线引用的归档材料，因此保留原文。其中关于 `feed.json` 是 Mac 日常输入、在仓库根目录采集/接受缓存/重建的旧说明已被增量流程取代。日常操作请遵循[当前生产流程](delta/README.md#producer-workflow)，使用仓库外的 staging 和可变缓存，不要修改固定基线或其引用的归档文件。
