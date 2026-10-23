from PySide6.QtWidgets import QPlainTextEdit
import json


class RawText(QPlainTextEdit):

    def __init__(self, content: dict):
        super().__init__()
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.content = content
        self.setPlainText(json.dumps(self.content, ensure_ascii=False, indent=4))

    def update_content(self) -> dict:
        self.content = json.loads(self.toPlainText())
        return self.content

    def overwrite(self, content: dict):
        self.content = content
        self.setPlainText(json.dumps(content, ensure_ascii=False, indent=4))
