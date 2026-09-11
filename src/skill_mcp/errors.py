class SkillMCPError(Exception):
    """Base class for errors that are safe to show to users and MCP clients."""


class SourceError(SkillMCPError):
    """A source could not be acquired or refreshed."""


class DiscoveryError(SkillMCPError):
    """No compatible skills could be discovered."""


class SkillNotFoundError(SkillMCPError):
    """A skill selector did not resolve."""


class AmbiguousSkillError(SkillMCPError):
    """A short skill name refers to more than one installed skill."""


class SecurityError(SkillMCPError):
    """A requested operation crossed a runtime security boundary."""


class RegistryError(SkillMCPError):
    """The persistent registry is invalid or unavailable."""
