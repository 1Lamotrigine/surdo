"""Проверки доступа к управлению словарём."""

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from accounts.models import Role


def can_manage_dictionary(user) -> bool:
    """Редактор, эксперт или администратор может работать со словарём.

    Публичный список проверенных жестов доступен всем; черновики и создание
    жестов — только этим ролям (ТЗ, FR-19/FR-20).
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_admin", False):
        return True
    return getattr(user, "role", None) in {
        Role.EDITOR,
        Role.EXPERT,
    }


def can_review_signs(user) -> bool:
    """Статус жеста (проверен/отклонён) ставит только эксперт или админ (B6)."""
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_admin", False) or getattr(user, "is_expert", False))


def dictionary_required(view: Callable):
    """Пускать в интерфейс редактора словаря: редактор, эксперт или админ."""

    @login_required
    @wraps(view)
    def wrapped(request: HttpRequest, *args, **kwargs):
        if not can_manage_dictionary(request.user):
            raise PermissionDenied("Доступ только для ролей словаря.")
        return view(request, *args, **kwargs)

    return wrapped


def review_required(view: Callable):
    """Пускать в интерфейс эксперта только эксперта-носителя и администратора."""

    @login_required
    @wraps(view)
    def wrapped(request: HttpRequest, *args, **kwargs):
        if not can_review_signs(request.user):
            raise PermissionDenied("Проверять жесты может только эксперт-носитель.")
        return view(request, *args, **kwargs)

    return wrapped
