def grater_zero(value):
    if value <= 0:
        return 'value must be greater zero'

    return None

def greate_equal_zero(value):
    if value < 0:
        return 'value must be qual or greater zero'

    return None

def json_content(content_type):
    if content_type != 'application/json':
        return 'invalid header: \'Content-Type\''
    
    return None