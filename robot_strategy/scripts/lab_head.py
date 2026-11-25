"""单项头部调试。默认预览，--run 逐项执行并记录目视结果。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("center", "nod", "shake"))
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--records", type=Path, default=Path("lab_records"))
    args = parser.parse_args()
    entry = Path(__file__).with_name("head_action.py")
    command = [sys.executable, "-X", "utf8", "-u", str(entry), args.action]
    if args.run:
        if not sys.stdin.isatty():
            parser.error("实机模式需要现场交互终端")
        if input("确认控制权、停止方式、声源转头状态及头部空间后，输入动作名执行：") != args.action:
            return 1
        command.append("--run")
    args.records.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".jsonl",
                                     prefix=args.action + "-", dir=str(args.records),
                                     delete=False) as record:
        def save(event):
            record.write(json.dumps(event, ensure_ascii=False) + "\n")
            record.flush()

        print("记录文件", record.name, flush=True)
        save({"mode": "robot" if args.run else "preview", "command": command})
        if args.run:
            command = ["timeout", "--signal=INT", "--kill-after=5", "25"] + command
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace") as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                save({"output": line.rstrip()})
            code = process.wait()
        save({"exit_code": code})
        if args.run:
            print("请确认机器人已停止，再记录现场表现。")
            observation = input("目视记录（方向、幅度、是否回到起始姿态，或填未观察）：")
            save({"observation": observation.strip() or "未观察"})
        return code


if __name__ == "__main__":
    sys.exit(main())
