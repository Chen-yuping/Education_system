from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Look up a dictionary key in a template: {{ mydict|get_item:key }}"""
    return dictionary.get(key)
