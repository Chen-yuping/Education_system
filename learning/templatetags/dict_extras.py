from django import template
import re

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Look up a dictionary key in a template: {{ mydict|get_item:key }}"""
    return dictionary.get(key)


@register.filter
def strip_choice_label(value):
    """去除选项开头的字母编号，保留正文并交由模板自动转义。"""
    if value is None:
        return ''
    return re.sub(r'^\s*[A-ZＡ-Ｚ][.．、)）]\s*', '', str(value), count=1)
