import json
from dataclasses import dataclass
from typing import Any, Optional

from argo_workflows.models import (
    ConfigMapKeySelector,
    EnvVar,
    EnvVarSource,
    ObjectFieldSelector,
    SecretKeySelector,
)


@dataclass
class ConfigMapNamedKey:
    """Config map representation. Supports the specification of a name/key string pair to identify a value"""

    config_map_name: str
    config_map_key: str


@dataclass
class SecretNamedKey:
    """Secret map representation. Supports the specification of a name/key string pair to identify a value"""

    secret_name: str
    secret_key: str


@dataclass
class EnvSpec:
    """Environment variable specification for tasks.

    Attributes
    ----------
    name: str
        The name of the variable.
    value: Optional[Any] = None
        The value of the variable. This value is serialized for the client. It is up to the client to deserialize the
        value in the task. In addition, if another type is passed, covered by `Any`, an attempt at `json.dumps` will be
        performed.
    value_from_input: Optional[str] = None
        A reference to an input parameter which will resolve to the value. The input parameter will be auto-generated.

    Raises
    ------
    AssertionError
        When the specified value is not JSON serializable.
    """

    name: str
    value: Optional[Any] = None
    value_from_input: Optional[str] = None

    def build(self) -> EnvVar:
        """Constructs and returns the Argo environment specification"""
        if self.value_from_input is not None:
            value = f"{{{{inputs.parameters.{self.name}}}}}"
        elif isinstance(self.value, str):
            value = self.value
        else:
            value = json.dumps(self.value)
        return EnvVar(name=self.name, value=value)


@dataclass
class SecretEnvSpec(EnvSpec, SecretNamedKey):
    """Environment variable specification from K8S secrets.

    Attributes
    ----------
    secret_name: str
        The name of the secret to load values from.
    secret_key: str
        The key of the value within the secret.
    """

    def build(self) -> EnvVar:
        """Constructs and returns the Argo environment specification"""
        return EnvVar(
            name=self.name,
            value_from=EnvVarSource(secret_key_ref=SecretKeySelector(name=self.secret_name, key=self.secret_key)),
        )


@dataclass
class ConfigMapEnvSpec(EnvSpec, ConfigMapNamedKey):
    """Environment variable specification from K8S config map.

    Attributes
    ----------
    config_map_name: str
        The name of the config map to load values from.
    config_map_key: str
        The key of the value within the config map.
    """

    def build(self) -> EnvVar:
        """Constructs and returns the Argo environment specification"""
        return EnvVar(
            name=self.name,
            value_from=EnvVarSource(
                config_map_key_ref=ConfigMapKeySelector(name=self.config_map_name, key=self.config_map_key)
            ),
        )


@dataclass
class FieldPath:
    """Field path representation.

    This allows obtaining K8S values via indexing into specific fields of the K8S definition.

    Attributes
    ----------
    field_path: str
        Path to the field to obtain the value from.
    """

    field_path: str


@dataclass
class FieldEnvSpec(EnvSpec, FieldPath):
    """Environment variable specification from K8S object field.

    Attributes
    ----------
    name: str
        The name of the variable.
    value: Optional[Any] = None
        The value of the variable. This value is serialized for the client. It is up to the client to deserialize the
        value in the task. In addition, if another type is passed, covered by `Any`, an attempt at `json.dumps` will be
        performed.
    value_from_input: Optional[str] = None
        A reference to an input parameter which will resolve to the value. The input parameter will be auto-generated.
    field_path: str
        Path to the field to obtain the value from.
    api_version: Optional[str] = 'v1'
        The version of the schema the FieldPath is written in terms of. Defaults to 'v1'.
    """

    api_version: Optional[str] = "v1"

    def build(self) -> EnvVar:
        """Constructs and returns the Argo environment specification"""
        return EnvVar(
            name=self.name,
            value_from=EnvVarSource(
                field_ref=ObjectFieldSelector(field_path=self.field_path, api_version=self.api_version)
            ),
        )
