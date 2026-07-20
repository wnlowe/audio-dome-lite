import os
import queue
import ffmpeg
from concurrent.futures import ThreadPoolExecutor
from settings_manager import Settings, Keys
from gui import ProgressBarWindow


class ffmpeg_queue():
    def __init__(self, jobs: list, job_type) -> None:
        self.jobs = jobs
        self.max_jobs = Settings.get_value(Keys.max_jobs) or os.cpu_count() or 4
        self.results = queue.Queue()
        self.completed = 0

        self.window = ProgressBarWindow(job_type, len(self.jobs))

        self.executor = ThreadPoolExecutor(max_workers=self.max_jobs)
        self.futures = [self.executor.submit(self._run_job, stream) for stream in self.jobs]

        self.window.after(50, self._poll_results)
        self.window.mainloop()

    def _run_job(self, stream) -> None:
        try:
            result = ffmpeg.run(stream, overwrite_output=True)
            self.results.put(("done", result))
        except ffmpeg.Error as error:
            self.results.put(("failed", error))

    def _poll_results(self) -> None:
        try:
            while True:
                status, payload = self.results.get_nowait()
                self.completed += 1
                if status == "done":
                    self._on_done(payload)
                else:
                    self._on_failed(payload)
        except queue.Empty:
            pass

        if self.completed >= len(self.jobs):
            self.window.destroy()
        else:
            self.window.after(50, self._poll_results)

    def _on_done(self, result) -> None:
        self.window.job_completed(result)

    def _on_failed(self, error: ffmpeg.Error) -> None:
        ...

    def wait(self) -> None:
        self.executor.shutdown(wait=True)