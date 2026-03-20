class LogView:
    @staticmethod
    def write_logs(run_log_path, err_log_path, full_log_path, full_err_path, stdout_text, stderr_text):
        with open(run_log_path, "w", encoding="utf-8") as f:
            f.write(stdout_text)
        with open(err_log_path, "w", encoding="utf-8") as f:
            f.write(stderr_text)
        with open(full_log_path, "a", encoding="utf-8") as f:
            f.write(stdout_text)
        with open(full_err_path, "a", encoding="utf-8") as f:
            f.write(stderr_text)
