# LabelS 前端工作区

![LabelS](./images/labels-logo.svg)

LabelS 的管理页面、标注组件和示例。上游来源与许可证说明见[根 README](../README.md#参考项目)。

`@labels/*` 是本仓库的本地包，使用 `workspace:*` 引用；未发布到 npm。开发和生产构建均使用工作区源码。

```bash
pnpm --config.strictDepBuilds=false install --frozen-lockfile --ignore-scripts
pnpm --filter @labels/frontend run postinstall
pnpm --filter @labels/frontend start --host 127.0.0.1
# Production build
pnpm build:frontend
```

| Package | Description |
| --- | --- |
| [@labels/image](./packages/image) | 图片标注引擎 |
| [@labels/i18n](./packages/i18n) | 国际化语言包 |
| [@labels/interface](./packages/interface) | 基础类型定义 |
| [@labels/formatter](./packages/formatter) | 数据格式化 |
| [@labels/components-react](./packages/components-react) | 基础 React 组件 |
| [@labels/image-annotator-react](./packages/image-annotator-react) | 图片标注套件 |
| [@labels/audio-react](./packages/audio-react) | 音频组件 |
| [@labels/audio-annotator-react](./packages/audio-annotator-react) | 音频标注套件 |
| [@labels/video-react](./packages/video-react) | 视频组件 |
| [@labels/video-annotator-react](./packages/video-annotator-react) | 视频标注套件 |

Apache-2.0. See [LICENSE](./LICENSE).
