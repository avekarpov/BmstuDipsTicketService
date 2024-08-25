class ErrorBase(BaseException):
    def __init__(self, message, code):
        self.message = message if type(message) is dict else {'message': message}
        self.code = code 


class UserError(ErrorBase):
    def __init__(self, message='bad request', code=400):
        super().__init__(message, code)


class ServerError(ErrorBase):
    def __init__(self, message='internal error', code=500):
        super().__init__(message, code)


class ErrorChain:
    def __init__(self, error_type, code_if_error):
        self._error_type = error_type
        self._code_if_error = code_if_error
        self._chain = []

    def __enter__(self):
        return self

    def add_error(self, error):
        self._chain.append(error)

    def __exit__(self, exception_type, exception_value, traceback):
        if exception_type is not None:
            raise exception_value

        if len(self._chain) != 0:
            message = {'error': 'bad request'}
            for chain in self._chain:
                message.update(chain)

            raise self._error_type(message, self._code_if_error)
