"""기체 프로파일 오류 — 문서 안 위치(JSON Pointer)를 함께 싣는다 (02 §5.6).

웹 편집기가 오류 문장만 받으면 사용자가 칸을 눈으로 찾아야 한다. 경로가 있으면 그 칸을 짚는다.
"""


class ProfileError(ValueError):
    def __init__(self, path: str, message: str):
        self.path = path or "/"
        self.message = message
        super().__init__(f"{self.path}: {message}")
