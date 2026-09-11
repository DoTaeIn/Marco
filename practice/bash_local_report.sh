#!/usr/bin/env bash
# 허가된 로컬 디렉터리를 읽기 전용으로 관찰해 Markdown 보고서를 만듭니다.
# 사용: bash practice/bash_local_report.sh --dir ./대상 [--keyword 오류] [--output ./report.md]

set -o nounset
set -o pipefail

readonly PROGRAM_NAME="$(basename "$0")"
readonly MAX_RESULTS=20

target_dir=""
keyword=""
output_file=""

usage() {
  cat <<EOF
사용법:
  bash $PROGRAM_NAME --dir <허가된_로컬_디렉터리> [--keyword <검색어>] [--output <보고서.md>]

옵션:
  --dir       관찰할 로컬 디렉터리 (필수, 읽기 전용)
  --keyword   텍스트 파일에서 찾을 키워드 (선택)
  --output    Markdown 보고서 경로 (기본: ./local-report.md)
  --help       이 도움말 표시
EOF
}

fail() {
  printf '오류: %s\n' "$1" >&2
  exit 1
}

require_value() {
  [[ $# -ge 2 ]] || fail "$1 옵션에는 값이 필요합니다."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      require_value "$@"
      target_dir="$2"
      shift 2
      ;;
    --keyword)
      require_value "$@"
      keyword="$2"
      shift 2
      ;;
    --output)
      require_value "$@"
      output_file="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "알 수 없는 옵션: $1"
      ;;
  esac
done

[[ -n "$target_dir" ]] || { usage >&2; fail "--dir 옵션은 필수입니다."; }
[[ -d "$target_dir" ]] || fail "디렉터리를 찾을 수 없습니다: $target_dir"

# 넓은 시스템 전체를 실수로 관찰하지 않도록 명시적으로 거절합니다.
[[ "$target_dir" != "/" ]] || fail "루트 디렉터리(/)는 대상이 될 수 없습니다. 더 좁은 로컬 경로를 지정하세요."

if [[ -z "$output_file" ]]; then
  output_file="./local-report.md"
fi

target_dir="$(cd "$target_dir" && pwd -P)"
output_dir="$(dirname "$output_file")"
[[ -d "$output_dir" ]] || fail "보고서를 저장할 디렉터리가 없습니다: $output_dir"
output_file="$(cd "$output_dir" && pwd -P)/$(basename "$output_file")"

temp_file="$(mktemp "${TMPDIR:-/tmp}/bash-local-report.XXXXXX")"
cleanup() { rm -f "$temp_file"; }
trap cleanup EXIT

file_count="$(find "$target_dir" -maxdepth 2 -type f -print 2>/dev/null | wc -l | tr -d ' ')"
dir_count="$(find "$target_dir" -maxdepth 2 -type d -print 2>/dev/null | wc -l | tr -d ' ')"
disk_line="$(df -h "$target_dir" | tail -n 1)"

{
  printf '# 로컬 디렉터리 관찰 보고서\n\n'
  printf -- '- 생성 시각: `%s`\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
  printf -- '- 대상: `%s`\n' "$target_dir"
  printf -- '- 관찰 방식: 읽기 전용 (대상 파일을 변경하지 않음)\n\n'

  printf '## 요약\n\n'
  printf -- '- 최대 깊이 2의 파일 수: `%s`\n' "$file_count"
  printf -- '- 최대 깊이 2의 디렉터리 수: `%s`\n' "$dir_count"
  printf -- '- 디스크 상태: `%s`\n\n' "$disk_line"

  printf '## 최근 수정된 파일 (최대 %s개)\n\n' "$MAX_RESULTS"
  printf '```text\n'
  find "$target_dir" -maxdepth 2 -type f -print0 2>/dev/null \
    | xargs -0 stat -f '%m %N' 2>/dev/null \
    | sort -rn \
    | head -n "$MAX_RESULTS" \
    | while IFS= read -r row; do
        timestamp="${row%% *}"
        path="${row#* }"
        printf '%s  %s\n' "$(date -r "$timestamp" '+%Y-%m-%d %H:%M:%S')" "$path"
      done
  printf '```\n\n'

  if [[ -n "$keyword" ]]; then
    printf '## 키워드 검색: `%s`\n\n' "$keyword"
    printf '```text\n'
    # -I: 이진 파일은 건너뜀. 결과 개수는 제한해 보고서를 작게 유지합니다.
    grep -R -I -n -- "$keyword" "$target_dir" 2>/dev/null | head -n "$MAX_RESULTS" || true
    printf '```\n'
  fi
} > "$temp_file"

mv "$temp_file" "$output_file"
trap - EXIT

printf '완료: %s\n' "$output_file"
