# LabelS Frontend workspace

![LabelS](./images/labels-logo.svg)

LabelS management pages, annotation components and examples. See the [root README](../README.md#参考项目) for upstream projects and licenses.

`@labels/*` packages are local to this repository, linked with `workspace:*`. They are not published on npm. Development and production builds use workspace sources.

```bash
pnpm --config.strictDepBuilds=false install --frozen-lockfile --ignore-scripts
pnpm --filter @labels/frontend run postinstall
pnpm --filter @labels/frontend start --host 127.0.0.1
# Production build
pnpm build:frontend
```

| Package | Description |
| --- | --- |
| [@labels/image](./packages/image) | Image annotation engine |
| [@labels/i18n](./packages/i18n) | Internationalization |
| [@labels/interface](./packages/interface) | Shared types |
| [@labels/formatter](./packages/formatter) | Data formatters |
| [@labels/components-react](./packages/components-react) | Shared React components |
| [@labels/image-annotator-react](./packages/image-annotator-react) | Image annotator |
| [@labels/audio-react](./packages/audio-react) | Audio components |
| [@labels/audio-annotator-react](./packages/audio-annotator-react) | Audio annotator |
| [@labels/video-react](./packages/video-react) | Video components |
| [@labels/video-annotator-react](./packages/video-annotator-react) | Video annotator |

Apache-2.0. See [LICENSE](./LICENSE).
