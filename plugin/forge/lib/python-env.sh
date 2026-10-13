# Окружение интерпретатора входа forge: ленивая сборка вне корня плагина.
#
# Подключается входом через `.` и объявляет одну функцию — `prepare_python_env`. Функция
# выставляет переменную PY: интерпретатор, которым вход запускает ядро.
#
# Если в файле зависимостей поставки нет ни одного пина, окружение не нужно, и PY — системный
# `python3`. Иначе окружение собирается один раз в каталоге данных плагина и несёт метку
# `.env-mark`: версию интерпретатора, способ сборки и sha256 файла зависимостей. Совпала
# версия и состав зависимостей — окружение используется повторно; не совпали — пересобирается.
#
# Способы перебираются в фиксированном порядке: `uv`, затем модуль `venv` интерпретатора.
# Окружение собирается во временном каталоге рядом с целевым и переименовывается в целевой
# только после успешной установки: прерванная сборка не оставляет полуготового окружения
# с меткой.
#
# Коды возврата функции: 0 — PY выставлен; 2 — интерпретатор не подходит или все способы
# сборки исчерпаны, диагностика напечатана в stderr.

FORGE_ENV_MIN_PYTHON="3.12"

prepare_python_env() {
    _forge_root=$1
    _forge_req="$_forge_root/src/requirements.txt"
    _forge_base=python3

    if ! command -v "$_forge_base" >/dev/null 2>&1; then
        printf 'forge: интерпретатор %s не найден в PATH\n' "$_forge_base" >&2
        return 2
    fi
    if ! "$_forge_base" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        printf 'forge: нужен %s %s или новее\n' "$_forge_base" "$FORGE_ENV_MIN_PYTHON" >&2
        return 2
    fi

    if [ ! -f "$_forge_req" ] || ! grep -q '^[^#[:space:]]' "$_forge_req"; then
        PY=$_forge_base
        return 0
    fi

    _forge_data=${CLAUDE_PLUGIN_DATA:-${XDG_CACHE_HOME:-$HOME/.cache}/forge-plugin}
    _forge_env="$_forge_data/env"
    _forge_pyver=$("$_forge_base" -c 'import platform; print(platform.python_version())')
    _forge_sum=$("$_forge_base" -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$_forge_req")

    if _forge_mark_matches "$_forge_env/.env-mark" "$_forge_pyver" "$_forge_sum" \
        && [ -x "$_forge_env/bin/python" ]; then
        PY="$_forge_env/bin/python"
        return 0
    fi

    mkdir -p "$_forge_data" || {
        printf 'forge: не удалось создать каталог окружения %s\n' "$_forge_data" >&2
        return 2
    }

    _forge_tried=""
    for _forge_method in uv venv; do
        _forge_tmp="$_forge_env.build.$$"
        rm -rf "$_forge_tmp"
        if _forge_build_"$_forge_method" "$_forge_base" "$_forge_tmp" "$_forge_req"; then
            printf 'python=%s\nmethod=%s\nrequirements=%s\n' \
                "$_forge_pyver" "$_forge_method" "$_forge_sum" >"$_forge_tmp/.env-mark"
            rm -rf "$_forge_env"
            mv "$_forge_tmp" "$_forge_env"
            PY="$_forge_env/bin/python"
            return 0
        fi
        rm -rf "$_forge_tmp"
        _forge_tried="$_forge_tried $_forge_method"
    done

    printf 'forge: не удалось собрать окружение зависимостей в %s\n' "$_forge_env" >&2
    printf 'forge: испробованы способы:%s\n' "$_forge_tried" >&2
    printf 'forge: установите uv либо модуль venv для %s и повторите вызов\n' "$_forge_base" >&2
    return 2
}

# Метка совпадает, если совпали версия интерпретатора и состав зависимостей. Способ сборки
# записан в метку для диагностики: сменить его можно только пересборкой, поэтому отдельно
# он не сравнивается.
_forge_mark_matches() {
    [ -f "$1" ] || return 1
    grep -qx "python=$2" "$1" && grep -qx "requirements=$3" "$1"
}

_forge_build_uv() {
    command -v uv >/dev/null 2>&1 || return 1
    uv venv --quiet --python "$1" "$2" >&2 \
        && uv pip install --quiet --python "$2/bin/python" -r "$3" >&2
}

_forge_build_venv() {
    "$1" -m venv "$2" >/dev/null 2>&1 || return 1
    "$2/bin/python" -m pip install --quiet --disable-pip-version-check -r "$3" >&2
}
