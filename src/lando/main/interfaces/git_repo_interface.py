class GitRepoInterface:
    def __init__(self, path):
        self.path = path

    def clone(self, pull_path):
        pass

    def push(self, push_path):
        pass
