from __future__ import annotations

import os
from collections.abc import Mapping

_GIT_REPOSITORY_VARIABLES = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_QUARANTINE_PATH",
    "GIT_WORK_TREE",
}


def subprocess_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment without inherited Git repository/difftool context.

    Provider authentication settings such as ``GIT_SSH_COMMAND`` remain intact.
    Repository location is supplied explicitly through the subprocess cwd and
    command arguments instead of ambient state from a parent Git hook or
    difftool.
    """

    environment = dict(os.environ if source is None else source)
    for name in tuple(environment):
        if name in _GIT_REPOSITORY_VARIABLES or name.startswith("GIT_DIFF"):
            environment.pop(name, None)
    return environment
