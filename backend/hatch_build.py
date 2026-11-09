"""发行包构建时打包前端；开发安装继续使用独立 Vite 服务。"""

import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):
    """从源码构建前端，或复用 sdist 中已经打包的资源，交给 Hatch 写入发行包。"""

    def initialize(self, version: str, build_data: dict) -> None:
        if version == "editable":
            return

        # 1. 源码构建始终重建页面，避免把旧 dist 静默带进新版本。
        root = Path(self.root)
        frontend = root.parent / "frontend"
        static = root / "statics"
        if (frontend / "package.json").is_file():
            pnpm = shutil.which("pnpm")
            if pnpm is None:
                raise RuntimeError("构建发行包需要 pnpm，请先准备 README 中的前端环境")
            subprocess.run([pnpm, "build:frontend"], cwd=frontend, check=True)
            static = frontend / "apps/frontend/dist"

        # 2. sdist 已携带资源，转换为 wheel 时无需 Node.js 或 pnpm。
        if not (static / "index.html").is_file():
            raise RuntimeError("发行包缺少前端 index.html，请从完整源码仓库构建")
        destination = "backend/statics" if self.target_name == "wheel" else "statics"
        build_data.setdefault("force_include", {})[str(static)] = destination
