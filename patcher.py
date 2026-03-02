#!/usr/bin/env python3
"""
Claude Code Vietnamese IME Fix

Fixes Vietnamese input bug in Claude Code CLI (npm and native) by patching
the backspace handling logic to also insert replacement text.

Usage:
  python3 patcher.py              Auto-detect and fix
  python3 patcher.py --restore    Restore from backup
  python3 patcher.py --path FILE  Fix specific file

Author: datnt (https://github.com/ntd4996)
Repository: https://github.com/ntd4996/claude-code-vietnamese-fix
License: MIT
"""

import os
import re
import sys
import shutil
import platform
import subprocess
from pathlib import Path
from datetime import datetime

PATCH_MARKER = "/* Vietnamese IME fix */"
DEL_CHAR = chr(127)  # 0x7F - actual DEL byte (npm version)


# ─────────────────────────── File detection ───────────────────────────

def is_binary_file(file_path):
    """Check if file is a binary executable (not a JS text file)."""
    with open(file_path, 'rb') as f:
        magic = f.read(4)
    # Mach-O (macOS): little-endian and big-endian variants
    mach_o = (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe',
              b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce')
    if magic in mach_o:
        return True
    # ELF (Linux)
    if magic[:4] == b'\x7fELF':
        return True
    # PE (Windows)
    if magic[:2] == b'MZ':
        return True
    return False


# ─────────────────────────── File discovery ───────────────────────────

def find_native_binary():
    """Find Claude Code native installation binary."""
    home = Path.home()

    if platform.system() in ('Darwin', 'Linux'):
        versions_dir = home / '.local' / 'share' / 'claude' / 'versions'
        if versions_dir.exists():
            versions = sorted(
                [v for v in versions_dir.iterdir()
                 if v.is_file() and '.backup' not in v.name],
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            if versions:
                return str(versions[0])

        # Try resolving symlink at known binary locations
        for bin_path in [Path('/usr/local/bin/claude'),
                         home / '.local' / 'bin' / 'claude']:
            if bin_path.is_symlink():
                target = bin_path.resolve()
                if target.exists() and target.is_file():
                    return str(target)

    raise FileNotFoundError("Không tìm thấy Claude Code native installation.")


def find_cli_js():
    """Auto-detect Claude Code location (native binary or npm cli.js)."""
    home = Path.home()
    is_windows = platform.system() == 'Windows'

    # Try native binary first (macOS / Linux)
    if not is_windows:
        try:
            return find_native_binary()
        except FileNotFoundError:
            pass

    # Fall back to npm installation
    if is_windows:
        search_dirs = [
            Path(os.environ.get('LOCALAPPDATA', '')) / 'npm-cache' / '_npx',
            Path(os.environ.get('APPDATA', '')) / 'npm' / 'node_modules',
        ]
    else:
        search_dirs = [
            home / '.npm' / '_npx',
            home / '.nvm' / 'versions' / 'node',
            Path('/usr/local/lib/node_modules'),
            Path('/opt/homebrew/lib/node_modules'),
        ]

    for d in search_dirs:
        if d.exists():
            for cli_js in d.rglob('*/@anthropic-ai/claude-code/cli.js'):
                return str(cli_js)

    raise FileNotFoundError(
        "Không tìm thấy Claude Code.\n"
        "Cài đặt: https://claude.ai/download hoặc npm install -g @anthropic-ai/claude-code"
    )


# ─────────────────────── Binary patching helpers ──────────────────────

def _find_one_bug_block(data, search_from):
    """Find a single bug block starting from search_from offset. Returns (abs_start, abs_end, block_str) or None."""
    hit = -1
    for pattern in (b'.includes("\\x7F")', b'.includes("\\x7f")'):
        pos = data.find(pattern, search_from)
        if pos != -1:
            if hit == -1 or pos < hit:
                hit = pos

    if hit == -1:
        return None

    region_start = max(0, hit - 300)
    region = data[region_start:hit + 600].decode('latin-1')

    local_idx = region.find('.includes("\\x7F")')
    if local_idx == -1:
        local_idx = region.find('.includes("\\x7f")')

    block_start = region.rfind('if(', 0, local_idx)
    if block_start == -1:
        return None

    depth = 0
    block_end = local_idx
    for i, ch in enumerate(region[block_start:block_start + 900]):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                block_end = block_start + i + 1
                break

    if depth != 0:
        return None

    abs_start = region_start + block_start
    abs_end = region_start + block_end
    return abs_start, abs_end, region[block_start:block_end]


def find_bug_blocks_binary(data):
    """Find ALL unpatched Vietnamese IME bug blocks in a native binary.

    Returns (unpatched_blocks, already_patched_count).
    Raises RuntimeError only when the pattern is completely absent.
    """
    unpatched = []
    patched_count = 0
    search_from = 0
    found_any = False

    while True:
        result = _find_one_bug_block(data, search_from)
        if result is None:
            break
        found_any = True
        abs_start, abs_end, block = result
        if 'for(const c of' in block and '.insert(c)' in block:
            patched_count += 1
            search_from = abs_end
            continue
        unpatched.append(result)
        search_from = abs_end

    if not found_any and patched_count == 0:
        raise RuntimeError(
            'Không tìm thấy bug pattern .includes("\\x7F").\n'
            "Claude Code có thể đã được Anthropic fix."
        )
    return unpatched, patched_count


def extract_variables_binary(block):
    """Extract dynamic variable names from a binary bug block."""
    # Input variable: INPUT.includes("\x7F")
    m_input = re.search(r'([\w$]+)\.includes\("\\x7[Ff]"', block)
    if not m_input:
        raise RuntimeError("Không trích xuất được input variable")
    inp = m_input.group(1)

    # count, state, cur_state
    m = re.search(
        r'let ([\w$]+)=\(' + re.escape(inp) +
        r'\.match\(/\\x7f/gi?\)\|\|\[\]\)\.length[,;]([\w$]+)=([\w$]+)[;,]',
        block, re.IGNORECASE
    )
    if not m:
        raise RuntimeError("Không trích xuất được biến count/state")
    state, cur_state = m.group(2), m.group(3)

    # update_text, update_offset
    m2 = re.search(
        rf'([\w$]+)\({re.escape(state)}\.text\);([\w$]+)\({re.escape(state)}\.offset\)',
        block
    )
    if not m2:
        raise RuntimeError("Không trích xuất được update functions")

    # key event variable: if(!KEY.backspace&&!KEY.delete&&
    m3 = re.search(r'if\(!([\w$]+)\.backspace&&!([\w$]+)\.delete&&', block)
    if not m3:
        raise RuntimeError("Không trích xuất được key event variable")
    key = m3.group(1)

    # extra calls between the last inner-if closing brace and return}
    m4 = re.search(r'\}([^{}]+?);return\}$', block)
    extra_calls = m4.group(1) if m4 else None

    return {
        'input': inp,
        'state': state,
        'cur_state': cur_state,
        'update_text': m2.group(1),
        'update_offset': m2.group(2),
        'key_event': key,
        'extra_calls': extra_calls,
    }


def generate_fix_binary(v, original_length):
    """Generate the binary-safe fix, padded to exactly original_length bytes."""
    key = v['key_event']
    inp = v['input']
    cur = v['cur_state']
    txt = v['update_text']
    off = v['update_offset']
    extra = v['extra_calls'] or ''

    # Pick a 1-char state variable that doesn't shadow the input variable
    # (avoids Temporal Dead Zone ReferenceError inside the let declaration)
    sv = next(c for c in '_qwertyuiop' if c != inp)

    fix = (
        f'if(!{key}.backspace&&!{key}.delete&&{inp}.includes("\\x7F"))'
        f'{{let {sv}={cur};'
        f'for(const c of {inp}){{{sv}=c==="\\x7F"?{sv}.backspace():{sv}.insert(c)}}'
        f'{cur}.text!=={sv}.text&&{txt}({sv}.text);'
        f'{off}({sv}.offset);'
    )
    if extra:
        fix += f'{extra};'
    fix += 'return}'

    fix_bytes = fix.encode('latin-1')
    padding = original_length - len(fix_bytes)

    if padding < 0:
        raise RuntimeError(
            f"Fix code ({len(fix_bytes)} bytes) dài hơn original ({original_length} bytes).\n"
            "Không thể patch binary này."
        )

    # Insert padding (spaces) just before 'return}' — valid, unreachable code
    fix_bytes = fix_bytes[:-len(b'return}')] + b' ' * padding + b'return}'
    assert len(fix_bytes) == original_length
    return fix_bytes


# ─────────────────────── Text patching helpers ────────────────────────

def find_bug_block(content):
    """Find the if-block containing the Vietnamese IME bug pattern (text mode)."""
    pattern = f'.includes("{DEL_CHAR}")'
    idx = content.find(pattern)

    if idx == -1:
        raise RuntimeError(
            'Không tìm thấy bug pattern .includes("\\x7f").\n'
            "Claude Code có thể đã được Anthropic fix."
        )

    block_start = content.rfind('if(', max(0, idx - 150), idx)
    if block_start == -1:
        raise RuntimeError("Không tìm thấy block if chứa pattern")

    depth = 0
    block_end = idx
    for i, c in enumerate(content[block_start:block_start + 800]):
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                block_end = block_start + i + 1
                break

    if depth != 0:
        raise RuntimeError("Không tìm thấy closing brace của block if")

    return block_start, block_end, content[block_start:block_end]


def extract_variables(block):
    """Extract dynamic variable names from the text-mode bug block."""
    normalized = block.replace(DEL_CHAR, '\\x7f')

    m = re.search(
        r'let ([\w$]+)=\(\w+\.match\(/\\x7f/g\)\|\|\[\]\)\.length[,;]([\w$]+)=([\w$]+)[;,]',
        normalized
    )
    if not m:
        raise RuntimeError("Không trích xuất được biến count/state")

    state, cur_state = m.group(2), m.group(3)

    m2 = re.search(
        rf'([\w$]+)\({re.escape(state)}\.text\);([\w$]+)\({re.escape(state)}\.offset\)',
        block
    )
    if not m2:
        raise RuntimeError("Không trích xuất được update functions")

    m3 = re.search(r'([\w$]+)\.includes\("', block)
    if not m3:
        raise RuntimeError("Không trích xuất được input variable")

    return {
        'input': m3.group(1),
        'state': state,
        'cur_state': cur_state,
        'update_text': m2.group(1),
        'update_offset': m2.group(2),
    }


def generate_fix(v):
    """Generate the fix code for text (npm) mode."""
    return (
        f'{PATCH_MARKER}'
        f'if({v["input"]}.includes("\\x7f")){{'
        f'let {v["state"]}={v["cur_state"]};'
        f'for(const _c of {v["input"]}){{{v["state"]}=_c==="\\x7f"?{v["state"]}.backspace():{v["state"]}.insert(_c)}}'
        f'if(!{v["cur_state"]}.equals({v["state"]})){{'
        f'if({v["cur_state"]}.text!=={v["state"]}.text)'
        f'{v["update_text"]}({v["state"]}.text);'
        f'{v["update_offset"]}({v["state"]}.offset)'
        f'}}return;}}'
    )


# ─────────────────────────── Code signing ────────────────────────────

def resign_binary(file_path):
    """Re-sign binary with ad-hoc signature after patching (macOS only)."""
    if platform.system() != 'Darwin':
        return
    if not shutil.which('codesign'):
        print("   Cảnh báo: codesign không tìm thấy, bỏ qua re-sign.", file=sys.stderr)
        return
    print("   Re-signing binary...")
    result = subprocess.run(
        ['codesign', '--force', '--sign', '-', file_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"codesign thất bại: {result.stderr.strip()}")
    print("   Re-sign thành công.")


# ─────────────────────────── Backup helpers ───────────────────────────

def find_latest_backup(file_path):
    """Find the most recent backup file."""
    dir_path = os.path.dirname(file_path) or '.'
    filename = os.path.basename(file_path)
    backups = [
        os.path.join(dir_path, f) for f in os.listdir(dir_path)
        if f.startswith(f"{filename}.backup-")
    ]
    if not backups:
        return None
    backups.sort(key=os.path.getmtime, reverse=True)
    return backups[0]


# ─────────────────────────── Main operations ──────────────────────────

def patch(file_path):
    """Apply Vietnamese IME fix to cli.js (text) or native binary."""
    print(f"-> File: {file_path}")

    if not os.path.exists(file_path):
        print(f"Lỗi: File không tồn tại: {file_path}", file=sys.stderr)
        return 1

    binary_mode = is_binary_file(file_path)

    # ── Binary patching path ──────────────────────────────────────────
    if binary_mode:
        print("   Chế độ: native binary")
        with open(file_path, 'rb') as f:
            data = f.read()

        try:
            blocks, already = find_bug_blocks_binary(data)
            if not blocks:
                print(f"Đã patch trước đó ({already} block(s)).")
                return 0

        except RuntimeError as e:
            print(f"\nLỗi: {e}", file=sys.stderr)
            return 1

        # Backup (only when there is actual work to do)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{file_path}.backup-{timestamp}"
        shutil.copy2(file_path, backup_path)
        print(f"   Backup: {backup_path}")

        try:
            print(f"   Tìm thấy {len(blocks)} bug block(s) cần patch"
                  + (f" ({already} đã patch)" if already else "") + ".")

            # Apply all fixes (iterate in reverse order so offsets stay valid)
            patched = bytearray(data)
            for abs_start, abs_end, block in sorted(blocks, key=lambda x: x[0], reverse=True):
                original_length = abs_end - abs_start
                print(f"   Block: offset={abs_start}, length={original_length}")

                variables = extract_variables_binary(block)
                print(f"   Vars: input={variables['input']}, state={variables['state']}, "
                      f"cur={variables['cur_state']}, key={variables['key_event']}")

                fix_bytes = generate_fix_binary(variables, original_length)
                patched[abs_start:abs_end] = fix_bytes

            patched = bytes(patched)
            with open(file_path, 'wb') as f:
                f.write(patched)

            # Verify
            with open(file_path, 'rb') as f:
                verified = f.read()
            if b'for(const c of' not in verified or b'.insert(c)' not in verified:
                raise RuntimeError("Verify failed: fix signature not found after write")

            resign_binary(file_path)

            print("\n   Patch thành công! Khởi động lại Claude Code.\n")
            return 0

        except Exception as e:
            print(f"\nLỗi: {e}", file=sys.stderr)
            print("Báo lỗi tại: https://github.com/ntd4996/claude-code-vietnamese-fix/issues",
                  file=sys.stderr)
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, file_path)
                os.remove(backup_path)
                print("Đã rollback về bản gốc.", file=sys.stderr)
            return 1

    # ── Text (npm) patching path ──────────────────────────────────────
    print("   Chế độ: npm / cli.js")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if PATCH_MARKER in content:
        print("Đã patch trước đó.")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{file_path}.backup-{timestamp}"
    shutil.copy2(file_path, backup_path)
    print(f"   Backup: {backup_path}")

    try:
        block_start, block_end, block = find_bug_block(content)
        variables = extract_variables(block)
        print(f"   Vars: input={variables['input']}, state={variables['state']}, "
              f"cur={variables['cur_state']}")

        fix_code = generate_fix(variables)
        patched = content[:block_start] + fix_code + content[block_end:]

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(patched)

        with open(file_path, 'r', encoding='utf-8') as f:
            if PATCH_MARKER not in f.read():
                raise RuntimeError("Verify failed: patch marker not found after write")

        print("\n   Patch thành công! Khởi động lại Claude Code.\n")
        return 0

    except Exception as e:
        print(f"\nLỗi: {e}", file=sys.stderr)
        print("Báo lỗi tại: https://github.com/ntd4996/claude-code-vietnamese-fix/issues",
              file=sys.stderr)
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, file_path)
            os.remove(backup_path)
            print("Đã rollback về bản gốc.", file=sys.stderr)
        return 1


def restore(file_path):
    """Restore file from latest backup."""
    backup = find_latest_backup(file_path)
    if not backup:
        print(f"Không tìm thấy backup cho {file_path}", file=sys.stderr)
        return 1

    shutil.copy2(backup, file_path)
    print(f"Đã khôi phục từ: {backup}")
    print("Khởi động lại Claude Code.")
    return 0


def show_help():
    print("Claude Code Vietnamese IME Fix")
    print("")
    print("Sử dụng:")
    print("  python3 patcher.py              Tự động phát hiện và fix")
    print("  python3 patcher.py --restore    Khôi phục từ backup")
    print("  python3 patcher.py --path FILE  Fix file cụ thể")
    print("  python3 patcher.py --help       Hiển thị hướng dẫn")
    print("")
    print("https://github.com/ntd4996/claude-code-vietnamese-fix")


def main():
    args = sys.argv[1:]

    if '--help' in args or '-h' in args:
        show_help()
        return 0

    if '--restore' in args:
        args.remove('--restore')
        file_path = None
        if '--path' in args:
            idx = args.index('--path')
            file_path = args[idx + 1]
        else:
            file_path = find_cli_js()
        return restore(file_path)

    file_path = None
    if '--path' in args:
        idx = args.index('--path')
        file_path = args[idx + 1]
    else:
        file_path = find_cli_js()

    return patch(file_path)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except FileNotFoundError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        sys.exit(1)
