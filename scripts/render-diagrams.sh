#!/usr/bin/env bash
# 把 docs/teaching/assets/diagrams/ 下全部 .mmd 渲染为同名 .png。
# 依赖:系统 Chrome(经 puppeteer-config.json 指定,npx 首次会下载 mermaid-cli 本体)。
set -euo pipefail

DIR="$(cd "$(dirname "$0")/../docs/teaching/assets/diagrams" && pwd)"
CHROME="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if [ ! -x "$CHROME" ]; then
    echo "未找到 Chrome:$CHROME(可用 CHROME_PATH 环境变量指定)" >&2
    exit 1
fi

cat > "$DIR/puppeteer-config.json" <<EOF
{
  "executablePath": "$CHROME",
  "args": ["--no-sandbox"]
}
EOF

shopt -s nullglob
mmds=("$DIR"/e*.mmd)
if [ ${#mmds[@]} -eq 0 ]; then
    echo "没有找到 e*.mmd 图源文件" >&2
    exit 1
fi

for src in "${mmds[@]}"; do
    out="${src%.mmd}.png"
    echo "渲染 $(basename "$src") -> $(basename "$out")"
    PUPPETEER_SKIP_DOWNLOAD=1 npx --yes @mermaid-js/mermaid-cli \
        -p "$DIR/puppeteer-config.json" \
        -i "$src" -o "$out" -b white -s 2 --quiet
done
echo "完成:共 ${#mmds[@]} 张"
