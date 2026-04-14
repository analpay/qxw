"""统一异常定义

所有自定义异常都应继承自 QxwError 基类，
便于统一的错误处理和用户友好的错误信息展示。
"""


class QxwError(Exception):
    """QXW 工具集基础异常类

    所有自定义异常都应继承此类。
    """

    def __init__(self, message: str, exit_code: int = 1) -> None:
        self.message = message
        self.exit_code = exit_code
        super().__init__(self.message)


class ConfigError(QxwError):
    """配置相关错误

    当配置文件缺失、格式错误或配置值无效时抛出。
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"配置错误: {message}", exit_code=2)


class DatabaseError(QxwError):
    """数据库相关错误

    当数据库连接失败、查询出错时抛出。
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"数据库错误: {message}", exit_code=3)


class CommandError(QxwError):
    """命令执行相关错误

    当命令参数无效或执行过程中出错时抛出。
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"命令错误: {message}", exit_code=4)


class NetworkError(QxwError):
    """网络相关错误

    当 API 调用失败、网络不可达时抛出。
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"网络错误: {message}", exit_code=5)


class ValidationError(QxwError):
    """数据校验错误

    当输入数据不符合预期格式时抛出。
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"校验错误: {message}", exit_code=6)
