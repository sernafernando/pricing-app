#!/usr/bin/env bash
# Sync skill metadata to AGENTS.md Auto-invoke sections
# Usage: ./sync.sh [--dry-run] [--scope <scope>]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"
SKILLS_DIR="$REPO_ROOT/skills"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Options
DRY_RUN=false
FILTER_SCOPE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --scope)
            FILTER_SCOPE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--scope <scope>]"
            echo ""
            echo "Options:"
            echo "  --dry-run    Show what would change without modifying files"
            echo "  --scope      Only sync specific scope (root, backend, frontend, ui, api, sdk)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Map scope to target docs path.
# Prefer AGENTS.md when present; fallback to CLAUDE.md in this repo.
# Legacy aliases (ui/api/sdk) are supported for compatibility.
get_agents_path() {
    local scope="$1"
    case "$scope" in
        root)
            echo "$REPO_ROOT/AGENTS.md"
            ;;
        backend)
            if [ -f "$REPO_ROOT/backend/AGENTS.md" ]; then
                echo "$REPO_ROOT/backend/AGENTS.md"
            else
                echo "$REPO_ROOT/backend/CLAUDE.md"
            fi
            ;;
        frontend)
            if [ -f "$REPO_ROOT/frontend/AGENTS.md" ]; then
                echo "$REPO_ROOT/frontend/AGENTS.md"
            else
                echo "$REPO_ROOT/frontend/CLAUDE.md"
            fi
            ;;
        # Legacy aliases used by older repos/tests
        ui)
            if [ -f "$REPO_ROOT/ui/AGENTS.md" ]; then
                echo "$REPO_ROOT/ui/AGENTS.md"
            elif [ -f "$REPO_ROOT/frontend/AGENTS.md" ]; then
                echo "$REPO_ROOT/frontend/AGENTS.md"
            else
                echo "$REPO_ROOT/frontend/CLAUDE.md"
            fi
            ;;
        api)
            if [ -f "$REPO_ROOT/api/AGENTS.md" ]; then
                echo "$REPO_ROOT/api/AGENTS.md"
            elif [ -f "$REPO_ROOT/backend/AGENTS.md" ]; then
                echo "$REPO_ROOT/backend/AGENTS.md"
            else
                echo "$REPO_ROOT/backend/CLAUDE.md"
            fi
            ;;
        sdk)
            if [ -f "$REPO_ROOT/prowler/AGENTS.md" ]; then
                echo "$REPO_ROOT/prowler/AGENTS.md"
            elif [ -f "$REPO_ROOT/sdk/AGENTS.md" ]; then
                echo "$REPO_ROOT/sdk/AGENTS.md"
            else
                echo ""
            fi
            ;;
        *)        echo "" ;;
    esac
}

# Extract YAML frontmatter field using awk
extract_field() {
    local file="$1"
    local field="$2"
    awk -v field="$field" '
        /^---$/ { in_frontmatter = !in_frontmatter; next }
        in_frontmatter && $1 == field":" {
            # Handle single line value
            sub(/^[^:]+:[[:space:]]*/, "")
            if ($0 != "" && $0 != ">") {
                gsub(/^["'\'']|["'\'']$/, "")  # Remove quotes
                print
                exit
            }
            # Handle multi-line value
            getline
            while (/^[[:space:]]/ && !/^---$/) {
                sub(/^[[:space:]]+/, "")
                printf "%s ", $0
                if (!getline) break
            }
            print ""
            exit
        }
    ' "$file" | sed 's/[[:space:]]*$//'
}

# Extract nested metadata field
#
# Supports either:
#   auto_invoke: "Single Action"
# or:
#   auto_invoke:
#     - "Action A"
#     - "Action B"
#
# For list values, this returns a pipe-delimited string: "Action A|Action B"
extract_metadata() {
    local file="$1"
    local field="$2"

    awk -v field="$field" '
        function trim(s) {
            sub(/^[[:space:]]+/, "", s)
            sub(/[[:space:]]+$/, "", s)
            return s
        }

        /^---$/ { in_frontmatter = !in_frontmatter; next }

        in_frontmatter && /^metadata:/ { in_metadata = 1; next }
        in_frontmatter && in_metadata && /^[a-z]/ && !/^[[:space:]]/ { in_metadata = 0 }

        in_frontmatter && in_metadata && $1 == field":" {
            # Remove "field:" prefix
            sub(/^[^:]+:[[:space:]]*/, "")

            # Single-line scalar: auto_invoke: "Action"
            if ($0 != "") {
                v = $0
                gsub(/^["'\'']|["'\'']$/, "", v)
                gsub(/^\[|\]$/, "", v)  # legacy: allow inline [a, b]
                print trim(v)
                exit
            }

            # Multi-line list:
            # auto_invoke:
            #   - "Action A"
            #   - "Action B"
            out = ""
            while (getline) {
                # Stop when leaving metadata block
                if (!in_frontmatter) break
                if (!in_metadata) break
                if ($0 ~ /^[a-z]/ && $0 !~ /^[[:space:]]/) break

                # On multi-line list, only accept "- item" lines. Anything else ends the list.
                line = $0
                if (line ~ /^[[:space:]]*-[[:space:]]*/) {
                    sub(/^[[:space:]]*-[[:space:]]*/, "", line)
                    line = trim(line)
                    gsub(/^["'\'']|["'\'']$/, "", line)
                    if (line != "") {
                        if (out == "") out = line
                        else out = out "|" line
                    }
                } else {
                    break
                }
            }

            if (out != "") print out
            exit
        }
    ' "$file"
}

echo -e "${BLUE}Skill Sync - Updating AGENTS.md Auto-invoke sections${NC}"
echo "========================================================"
echo ""

# Collect skills by target file.
# FILE_SKILLS maps absolute target file -> "skill1:action1|skill2:action2|..."
# FILE_SCOPES maps absolute target file -> "scope1,scope2,..." (for logging)
declare -A FILE_SKILLS
declare -A FILE_SCOPES

# Deterministic iteration order (stable diffs)
# Note: macOS ships BSD find; avoid GNU-only flags.
while IFS= read -r skill_file; do
    [ -f "$skill_file" ] || continue

    skill_name=$(extract_field "$skill_file" "name")
    scope_raw=$(extract_metadata "$skill_file" "scope")

    auto_invoke_raw=$(extract_metadata "$skill_file" "auto_invoke")
    # extract_metadata() returns:
    # - single action: "Action"
    # - multiple actions: "Action A|Action B" (pipe-delimited)
    # But SCOPE_SKILLS also uses '|' to separate entries, so we protect it.
    auto_invoke=${auto_invoke_raw//|/;;}

    # Skip if no scope or auto_invoke defined
    [ -z "$scope_raw" ] || [ -z "$auto_invoke" ] && continue

    # Parse scope (can be comma-separated or space-separated)
    IFS=', ' read -ra scopes <<< "$scope_raw"

    for scope in "${scopes[@]}"; do
        scope=$(echo "$scope" | tr -d '[:space:]')
        [ -z "$scope" ] && continue

        # Filter by scope if specified
        [ -n "$FILTER_SCOPE" ] && [ "$scope" != "$FILTER_SCOPE" ] && continue

        agents_path=$(get_agents_path "$scope")
        if [ -z "$agents_path" ] || [ ! -f "$agents_path" ]; then
            echo -e "${YELLOW}Warning: No AGENTS.md found for scope '$scope'${NC}"
            continue
        fi

        # Append to target file's skill list
        if [ -z "${FILE_SKILLS[$agents_path]}" ]; then
            FILE_SKILLS[$agents_path]="$skill_name:$auto_invoke"
        else
            FILE_SKILLS[$agents_path]="${FILE_SKILLS[$agents_path]}|$skill_name:$auto_invoke"
        fi

        # Track contributing scopes for logging
        if [ -z "${FILE_SCOPES[$agents_path]}" ]; then
            FILE_SCOPES[$agents_path]="$scope"
        else
            case ",${FILE_SCOPES[$agents_path]}," in
                *",$scope,"*) ;;
                *) FILE_SCOPES[$agents_path]="${FILE_SCOPES[$agents_path]},$scope" ;;
            esac
        fi
    done
done < <(find "$SKILLS_DIR" -mindepth 2 -maxdepth 2 -name SKILL.md -print | sort)

# Generate Auto-invoke section for each target file.
# Deterministic file order (stable diffs)
files_sorted=()
while IFS= read -r file_path; do
    files_sorted+=("$file_path")
done < <(printf "%s\n" "${!FILE_SKILLS[@]}" | sort)

for agents_path in "${files_sorted[@]}"; do
    scopes_for_file="${FILE_SCOPES[$agents_path]}"
    display_path="${agents_path#$REPO_ROOT/}"
    echo -e "${BLUE}Processing: $scopes_for_file -> $display_path${NC}"

    # Build the Auto-invoke table
    auto_invoke_section="### Auto-invoke Skills

When performing these actions, ALWAYS invoke the corresponding skill FIRST:

| Action | Skill |
|--------|-------|"

    # Expand into sortable rows: "action<TAB>skill"
    rows=()

    IFS='|' read -ra skill_entries <<< "${FILE_SKILLS[$agents_path]}"
    for entry in "${skill_entries[@]}"; do
        skill_name="${entry%%:*}"
        actions_raw="${entry#*:}"

        actions_raw=${actions_raw//;;/|}
        IFS='|' read -ra actions <<< "$actions_raw"
        for action in "${actions[@]}"; do
            action="$(echo "$action" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
            [ -z "$action" ] && continue
            rows+=("$action	$skill_name")
        done
    done

    # Deterministic row order: Action then Skill
    while IFS=$'\t' read -r action skill_name; do
        [ -z "$action" ] && continue
        auto_invoke_section="$auto_invoke_section
| $action | \`$skill_name\` |"
    done < <(printf "%s\n" "${rows[@]}" | LC_ALL=C sort -u -t $'\t' -k1,1 -k2,2)

    if $DRY_RUN; then
        echo -e "${YELLOW}[DRY RUN] Would update $agents_path with:${NC}"
        echo "$auto_invoke_section"
        echo ""
    else
        # Write new section to temp file (avoids awk multi-line string issues on macOS)
        section_file=$(mktemp)
        echo "$auto_invoke_section" > "$section_file"

        # Check if Auto-invoke section exists
        if grep -q "### Auto-invoke Skills" "$agents_path"; then
            # Replace existing section (up to next --- or ## heading)
            awk '
                /^### Auto-invoke Skills/ {
                    while ((getline line < "'"$section_file"'") > 0) print line
                    close("'"$section_file"'")
                    skip = 1
                    next
                }
                skip && /^(---|## )/ {
                    skip = 0
                    print ""
                }
                !skip { print }
            ' "$agents_path" > "$agents_path.tmp"
            mv "$agents_path.tmp" "$agents_path"
            echo -e "${GREEN}  ✓ Updated Auto-invoke section${NC}"
        else
            # Insert after Skills Reference blockquote
            awk '
                /^>.*SKILL\.md\)$/ && !inserted {
                    print
                    getline
                    if (/^$/) {
                        print ""
                        while ((getline line < "'"$section_file"'") > 0) print line
                        close("'"$section_file"'")
                        print ""
                        inserted = 1
                        next
                    }
                }
                { print }
            ' "$agents_path" > "$agents_path.tmp"

            # Fallback: if no Skills Reference block exists, append section at EOF.
            if ! grep -q "### Auto-invoke Skills" "$agents_path.tmp"; then
                printf "\n%s\n" "$auto_invoke_section" >> "$agents_path.tmp"
            fi

            mv "$agents_path.tmp" "$agents_path"
            echo -e "${GREEN}  ✓ Inserted Auto-invoke section${NC}"
        fi

        rm -f "$section_file"
    fi
done

echo ""
echo -e "${GREEN}Done!${NC}"

# Show skills without metadata
echo ""
echo -e "${BLUE}Skills missing sync metadata:${NC}"
missing=0
while IFS= read -r skill_file; do
    [ -f "$skill_file" ] || continue
    skill_name=$(extract_field "$skill_file" "name")
    scope_raw=$(extract_metadata "$skill_file" "scope")
    auto_invoke_raw=$(extract_metadata "$skill_file" "auto_invoke")
    auto_invoke=${auto_invoke_raw//|/;;}

    if [ -z "$scope_raw" ] || [ -z "$auto_invoke" ]; then
        echo -e "  ${YELLOW}$skill_name${NC} - missing: ${scope_raw:+}${scope_raw:-scope} ${auto_invoke:+}${auto_invoke:-auto_invoke}"
        missing=$((missing + 1))
    fi
done < <(find "$SKILLS_DIR" -mindepth 2 -maxdepth 2 -name SKILL.md -print | sort)

if [ $missing -eq 0 ]; then
    echo -e "  ${GREEN}All skills have sync metadata${NC}"
fi
