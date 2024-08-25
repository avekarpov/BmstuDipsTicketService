import errors


class Value:
    @staticmethod
    def get_from(value_type, error_type, source, name, error_chain, code):
        if name not in source.keys():
            message = {name: f'Missed required arg'}

            if error_chain is not None:
                error_chain.add_error(message)
                return value_type(name, None, error_chain)

            raise error_type(message, code)
        
        return value_type(name, source[name], error_chain)

    def __init__(self, error_type, name, value, error_chain):
        self._error_type = error_type
        self._type = self.__class__.__name__

        self.value = value
        self.name = name

        self._error_chain = error_chain

        self._failed = self.value is None

    def _is_error_chain(self):
        return self._error_chain is not None

    def _make_error(self, message, code):
        self._failed = True

        if self._is_error_chain():
            self._error_chain.add_error(message)
            return self
        
        raise self._error_type(message, code)

    def expected(self, expected_type, code):
        if self._failed:
            return self

        if type(self.value) is not expected_type:
            return self._make_error({self.name: 'Invalid type for arg'}, code)

        return self
        
    def rule(self, rule, code):
        if self._failed:
            return self

        result = rule(self.value)

        if result is not None:
            return self._make_error({self.name: result}, code)
        
        return self


    def cast_to(self, expected_type, code):
        if self._failed:
            return self

        try:
            self.value = expected_type(self.value)

        except (ValueError, TypeError) as error:
            return self._make_error({self.name: 'Invalid type for arg'}, code)
        
        return self
        
    def cast_to_int(self, code):
        return self.cast_to(int, code)
    

class UserValue(Value):
    class ErrorChain(errors.ErrorChain):
        def __init__(self, code=400):
            super().__init__(errors.UserError, code)

    @staticmethod
    def get_from(source, name, error_chain=None, code=400) -> 'UserValue':
        return Value.get_from(UserValue, errors.UserError, source, name, error_chain, code)

    def __init__(self, name, value, error_chain=None):
        super().__init__(errors.UserError, name, value, error_chain)

    def expected(self, expected_type, code=400) -> 'UserValue':
        return super().expected(expected_type, code)

    def rule(self, rule, code=400) -> 'UserValue':
        return super().rule(rule, code)

    def cast_to(self, expected_type, code=400) -> 'UserValue':
        return super().cast_to(expected_type, code)

    def cast_to_int(self, code=400) -> 'UserValue':
        return super().cast_to_int(code)


class ServerValue(Value):
    @staticmethod
    def get_from(source, name, error_chain=None, code=500) -> 'ServerValue':
        return Value.get_from(ServerValue, errors.ServerError, source, name, error_chain, code)

    def __init__(self, name, value, erro_chain=None):
        super().__init__(errors.ServerError, name, value, erro_chain)

    def expected(self, expected_type, code=500) -> 'ServerValue':
        return super().expected(expected_type, code)

    def rule(self, rule, code=500) -> 'ServerValue':
        return super().rule(rule, code)

    def cast_to(self, expected_type, code=500) -> 'ServerValue':
        return super().cast_to(expected_type, code)
    
    def cast_to_int(self, code=500) -> 'ServerValue':
        return super().cast_to_int(code)
