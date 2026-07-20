import tkinter as tk
from tkinter import ttk

class ProgressBarWindow(tk.Tk):
    def __init__(self, job_type, job_count:int):
        super().__init__()
        if "_" in job_type:
            self.job_type = " ".join(word.capitalize() for word in job_type.split("_"))
        else:
            self.job_type = job_type.capitalize()
        self.title(f"Audio Dome Lite Job: {self.job_type}")
        
        
        ttk.Label(self, text="An Audio Dome Lite Job is in Progress").pack(side="top", fill="x")
        ttk.Label(self, text=f"Job Type: {self.job_type}").pack(side="top", fill="x")
        
        bar = ttk.Progressbar(self, mode="determinate", maximum=job_count, length=280)
        bar.pack(side="top", fill="x")
        self.progress = tk.IntVar(value=0)
        self.completed_jobs = 0
        bar.configure(variable=self.progress)
        
    def job_completed(self, result):
        self.completed_jobs += 1
        self.progress.set(self.completed_jobs)