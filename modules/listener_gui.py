# listener_gui.py
import re
import tkinter as tk
from tkinter import scrolledtext
import multiprocessing as mp
import threading
import queue
import json
import time


class ListenerGUI:
    def __init__(self, title: str = "ListenerRegion Output"):
        self.title = title
        self.root = tk.Tk()
        self.root.title(self.title)
        self.root.geometry("900x700")

        # Configure dark theme
        self.root.configure(bg='#1e1e1e')

        # Create frame for text area
        self.text_frame = tk.Frame(self.root, bg='#1e1e1e')
        self.text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ScrolledText widget with dark theme
        self.text_area = scrolledtext.ScrolledText(
            self.text_frame,
            wrap=tk.WORD,
            state='disabled',
            bg='#000000',  # Black background
            fg='#ffffff',  # White text
            insertbackground='#ffffff',  # White cursor
            font=('Consolas', 11)
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)

        # Configure tags for syntax highlighting
        self.text_area.tag_configure("key", foreground="#ff9999")  # Light red for keys
        self.text_area.tag_configure("string", foreground="#99ff99")  # Light green for string values
        self.text_area.tag_configure("number", foreground="#99ff99")  # Light green for numbers
        self.text_area.tag_configure("boolean", foreground="#99ff99")  # Light green for booleans
        self.text_area.tag_configure("null", foreground="#99ff99")  # Light green for null
        self.text_area.tag_configure("brace", foreground="#ffffff")  # White for braces/brackets
        self.text_area.tag_configure("punctuation", foreground="#ffffff")  # White for colons

        # Thread-safe queue for communication between process and GUI
        self.message_queue = queue.Queue()

        # Flags for thread management
        self.running = True
        self.receiving = True

    def append_message(self, message: str):
        """Thread-safe method to append a message to the text area."""
        self.message_queue.put(message)

    def _insert_with_highlighting(self, text: str) -> None:
        """Insert text with syntax highlighting."""
        # Enable text area for editing
        self.text_area.config(state='normal')

        # Get current end position before insertion
        start_pos = self.text_area.index(tk.END + "-1c")

        # Insert the text
        self.text_area.insert(tk.END, text + "\n\n")

        # Apply syntax highlighting to the newly inserted text
        self._apply_syntax_highlighting(start_pos, tk.END + "-1c")

        # Disable text area again
        self.text_area.config(state='disabled')
        self.text_area.see(tk.END)

    def _apply_syntax_highlighting(self, start_pos: str, end_pos: str) -> None:
        """Apply syntax highlighting to text between start_pos and end_pos."""
        # Get the text content
        content = self.text_area.get(start_pos, end_pos)

        # Clear existing tags in this range
        for tag in ["key", "string", "number", "boolean", "null", "brace", "punctuation"]:
            self.text_area.tag_remove(tag, start_pos, end_pos)

        # Highlight keys (text before colons)
        for match in re.finditer(r'"([^"\\]*(\\.[^"\\]*)*)"\s*:', content):
            key_start = f"{start_pos}+{match.start(1)} chars"
            key_end = f"{start_pos}+{match.end(1)} chars"
            self.text_area.tag_add("key", key_start, key_end)

            # Highlight the colon and surrounding whitespace
            colon_start = f"{start_pos}+{match.end(1)} chars"
            colon_end = f"{start_pos}+{match.end()} chars"
            self.text_area.tag_add("punctuation", colon_start, colon_end)

        # Highlight string values
        for match in re.finditer(r':\s*"([^"\\]*(\\.[^"\\]*)*)"', content):
            value_start = f"{start_pos}+{match.start(1)} chars"
            value_end = f"{start_pos}+{match.end(1)} chars"
            self.text_area.tag_add("string", value_start, value_end)

        # Highlight numbers
        for match in re.finditer(r':\s*(-?\d+(\.\d+)?)', content):
            value_start = f"{start_pos}+{match.start(1)} chars"
            value_end = f"{start_pos}+{match.end(1)} chars"
            self.text_area.tag_add("number", value_start, value_end)

        # Highlight booleans
        for match in re.finditer(r':\s*(true|false)', content):
            value_start = f"{start_pos}+{match.start(1)} chars"
            value_end = f"{start_pos}+{match.end(1)} chars"
            self.text_area.tag_add("boolean", value_start, value_end)

        # Highlight null
        for match in re.finditer(r':\s*(null)', content):
            value_start = f"{start_pos}+{match.start(1)} chars"
            value_end = f"{start_pos}+{match.end(1)} chars"
            self.text_area.tag_add("null", value_start, value_end)

        # Highlight braces and brackets
        for match in re.finditer(r'[\{\}\[\]]', content):
            char_pos = f"{start_pos}+{match.start()} chars"
            self.text_area.tag_add("brace", char_pos, f"{start_pos}+{match.end()} chars")

    def update_text_area(self):
        """Update the GUI text area from the message queue."""
        try:
            while True:
                message = self.message_queue.get_nowait()

                # Check for sentinel value
                if message is None:
                    self.receiving = False
                    # Add a final message indicating end of stream
                    self._insert_with_highlighting("--- END OF MESSAGE STREAM ---")
                    continue  # Continue processing to drain any remaining messages

                # Format the message nicely
                try:
                    if isinstance(message, dict):
                        formatted = json.dumps(message, indent=2, ensure_ascii=False)
                    else:
                        formatted = str(message)
                except Exception:
                    formatted = str(message)

                # Insert with highlighting
                self._insert_with_highlighting(formatted)

        except queue.Empty:
            pass

        # Continue updating if still running
        if self.running:
            self.root.after(100, self.update_text_area)  # Check again in 100ms

    def run(self):
        """Start the GUI mainloop."""
        self.update_text_area()
        self.root.mainloop()

    def stop(self):
        """Stop the GUI loop gracefully."""
        self.receiving = False
        self.running = False
        # Don't call root.quit() here to allow manual closing

    def is_receiving(self):
        """Check if still receiving messages."""
        return self.receiving


def handle_output(q: mp.Queue, gui: ListenerGUI):
    """
    Output process function that reads from the queue and sends messages to the GUI.
    Stops when it receives None but keeps the GUI running for review.
    """
    while True:
        try:
            msg = q.get(timeout=1.0)  # Use timeout to allow periodic checking
            if msg is None:
                # Send sentinel to GUI to indicate end of stream
                gui.append_message(None)
                break
            gui.append_message(msg)
        except queue.Empty:
            # Check if GUI is still running
            if not gui.is_receiving():
                break
            continue
    # Thread can safely exit here - GUI remains open for review


def mock_sender(q: mp.Queue):
    for i in range(10):
        q.put({
            "message": f"Test message {i}",
            "source": "test_region",
            "destination": "listener",
            "timestamp": 1234567890,
            "active": True,
            "count": i,
            "data": None
        })
        time.sleep(1)
    q.put(None)  # Sentinel to stop

if __name__ == "__main__":
    # Example usage with a mock queue sender (for testing)

    # Create GUI
    gui = ListenerGUI("ListenerRegion Monitor")

    # Create queue and start mock sender
    out_q = mp.Queue()
    sender_process = mp.Process(target=mock_sender, args=(out_q,))
    sender_process.start()

    # Start output handler in a thread (because tkinter isn't fork-safe)
    output_thread = threading.Thread(target=handle_output, args=(out_q, gui), daemon=True)
    output_thread.start()

    # Run GUI - window stays open after receiving None
    print("GUI started. Window will remain open after message stream ends for review.")
    print("Close the window manually to exit.")
    gui.run()

    # Cleanup when window is closed
    gui.stop()
    sender_process.join(timeout=2.0)
    if sender_process.is_alive():
        sender_process.terminate()

    print("Application terminated.")