class ConsoleView:
    def section(self, title: str):
        print(f"\n{'='*60}")
        print(f"{title}")
        print(f"{'='*60}\n")

    def print_text(self, text: str):
        print(text)

    def print_stdout(self, text: str):
        if text:
            print(text, end="" if text.endswith("\n") else "\n")

    def print_stderr(self, text: str):
        if text:
            import sys
            print(text, end="" if text.endswith("\n") else "\n", file=sys.stderr)
