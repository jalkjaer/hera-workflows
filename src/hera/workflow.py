"""The implementation of a Hera workflow for Argo-based workflows"""
from typing import Dict, List, Optional, Tuple, Union

from argo_workflows.models import (
    IoArgoprojWorkflowV1alpha1Arguments,
    IoArgoprojWorkflowV1alpha1VolumeClaimGC,
    IoArgoprojWorkflowV1alpha1Workflow,
    IoArgoprojWorkflowV1alpha1WorkflowSpec,
    LocalObjectReference,
    ObjectMeta,
)

import hera
from hera.affinity import Affinity
from hera.dag import DAG
from hera.host_alias import HostAlias
from hera.parameter import Parameter
from hera.security_context import WorkflowSecurityContext
from hera.task import Task
from hera.toleration import Toleration
from hera.ttl_strategy import TTLStrategy
from hera.validators import validate_name
from hera.volume_claim_gc import VolumeClaimGCStrategy
from hera.workflow_editors import add_task, add_tasks
from hera.workflow_service import WorkflowService


class Workflow:
    """A workflow representation.

    The workflow is used as a functional representation for a collection of tasks and
    steps. The workflow context controls the overall behaviour of tasks, such as whether to notify completion, whether
    to execute retires, overall parallelism, etc. The workflow can be constructed and submitted to multiple Argo
    endpoints as long as a token can be associated with the endpoint at the given domain.

    Parameters
    ----------
    name: str
        The workflow name. Note that the workflow initiation will replace underscores with dashes.
    service: Optional[WorkflowService] = None
        A workflow service to use for submissions. See `hera.v1.workflow_service.WorkflowService`.
    parallelism: Optional[int] = None
        The number of parallel tasks to run in case a task group is executed for multiple tasks.
    service_account_name: Optional[str] = None,
        The name of the service account to use in all workflow tasks.
    labels: Optional[Dict[str, str]] = None
        A dictionary of labels to attach to the Workflow object metadata.
    annotations: Optional[Dict[str, str]] = None
        A dictionary of annotations to attach to the Workflow object metadata.
    security_context: Optional[WorkflowSecurityContext] = None
        Define security settings for all containers in the workflow.
    image_pull_secrets: Optional[List[str]] = None
        A list of image pull secrets. This is used to authenticate with the private image registry of the images
        used by tasks.
    workflow_template_ref: Optional[str] = None
        The name of the workflowTemplate reference. WorkflowTemplateRef is a reference to a WorkflowTemplate resource.
        If you create a WorkflowTemplate resource either clusterWorkflowTemplate or not (clusterScope attribute bool)
        you can reference it again and again when you create a new Workflow without specifying the same tasks and
        dependencies. Official doc: https://argoproj.github.io/argo-workflows/fields/#workflowtemplateref
    ttl_strategy: Optional[TTLStrategy] = None
        The time to live strategy of the workflow.
    volume_claim_gc_strategy: Optional[VolumeClaimGCStrategy] = None
        Define how to delete volumes from completed Workflows.
    host_aliases: Optional[List[HostAlias]] = None
        Mappings between IP and hostnames.
    node_selectors: Optional[Dict[str, str]] = None
        A collection of key value pairs that denote node selectors. This is used for scheduling purposes. If the task
        requires GPU resources, clients are encouraged to add a node selector for a node that can satisfy the
        requested resources. In addition, clients are encouraged to specify a GPU toleration, depending on the platform
        they submit the workflow to.
    affinity: Optional[Affinity] = None
        The task affinity. This dictates the scheduling protocol of the pods running the tasks of the workflow.
    dag: Optional[DAG] = None
        The DAG to execute as part of the workflow.
    parameters: Optional[List[Parameter]] = None
        Any global parameters for the workflow.
    tolerations: Optional[List[Toleration]] = None
        List of tolerations for the pod executing the task. This is used for scheduling purposes.
    """

    def __init__(
        self,
        name: str,
        service: Optional[WorkflowService] = None,
        parallelism: Optional[int] = None,
        service_account_name: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        annotations: Optional[Dict[str, str]] = None,
        security_context: Optional[WorkflowSecurityContext] = None,
        image_pull_secrets: Optional[List[str]] = None,
        workflow_template_ref: Optional[str] = None,
        ttl_strategy: Optional[TTLStrategy] = None,
        volume_claim_gc_strategy: Optional[VolumeClaimGCStrategy] = None,
        host_aliases: Optional[List[HostAlias]] = None,
        node_selectors: Optional[Dict[str, str]] = None,
        affinity: Optional[Affinity] = None,
        dag: Optional[DAG] = None,
        parameters: Optional[List[Parameter]] = None,
        tolerations: Optional[List[Toleration]] = None,
    ):
        self.name = validate_name(name)
        self.service = service or WorkflowService()
        self.parallelism = parallelism
        self.security_context = security_context
        self.service_account_name = service_account_name
        self.labels = labels
        self.annotations = annotations
        self.image_pull_secrets = image_pull_secrets
        self.workflow_template_ref = workflow_template_ref
        self.node_selector = node_selectors
        self.ttl_strategy = ttl_strategy
        self.affinity = affinity
        self.parameters = parameters
        self.tolerations = tolerations
        self.in_context = False
        self.volume_claim_gc_strategy = volume_claim_gc_strategy
        self.host_aliases = host_aliases
        self.dag = dag
        self.exit_task: Optional[str] = None
        self.tasks: List["Task"] = []

    def _build_metadata(self, use_name=True) -> ObjectMeta:
        """Assembles the metadata of the workflow"""
        metadata = ObjectMeta()
        if use_name:
            setattr(metadata, "name", self.name)
        if self.labels:
            setattr(metadata, "labels", self.labels)
        if self.annotations:
            setattr(metadata, "annotations", self.annotations)
        return metadata

    def _build_spec(self, workflow_template: bool = False) -> IoArgoprojWorkflowV1alpha1WorkflowSpec:
        """Assembles the spec of the workflow"""
        # Main difference between workflow and workflow template spec is that WT
        # (generally) doesn't have an entrypoint
        assert self.dag is not None
        spec = IoArgoprojWorkflowV1alpha1WorkflowSpec()
        templates = self.dag._build_templates()

        if not workflow_template:
            templates += self.dag.build()
            setattr(spec, "entrypoint", self.name)

        setattr(spec, "templates", templates)

        if self.parallelism is not None:
            setattr(spec, "parallelism", self.parallelism)

        if self.ttl_strategy is not None:
            setattr(spec, "ttl_strategy", self.ttl_strategy.build())

        if self.volume_claim_gc_strategy is not None:
            setattr(
                spec,
                "volume_claim_gc",
                IoArgoprojWorkflowV1alpha1VolumeClaimGC(strategy=self.volume_claim_gc_strategy.value),
            )

        if self.host_aliases is not None:
            setattr(spec, "host_aliases", [h.argo_host_alias for h in self.host_aliases])

        if self.security_context is not None:
            security_context = self.security_context.get_security_context()
            setattr(spec, "security_context", security_context)

        if self.service_account_name is not None:
            # setattr(main_template, "service_account_name", self.service_account_name) #TODO Is this needed?
            setattr(spec, "service_account_name", self.service_account_name)

        if self.image_pull_secrets is not None:
            secret_refs = [LocalObjectReference(name=name) for name in self.image_pull_secrets]
            setattr(spec, "image_pull_secrets", secret_refs)

        if self.parameters is not None:
            setattr(
                spec,
                "arguments",
                IoArgoprojWorkflowV1alpha1Arguments(parameters=[p.as_argument() for p in self.parameters]),
            )

        if self.affinity is not None:
            setattr(spec, "affinity", self.affinity._build())

        if self.node_selector is not None:
            setattr(spec, "node_selector", self.node_selector)

        if self.tolerations is not None:
            ts = [t.build() for t in self.tolerations]
            setattr(spec, "tolerations", ts)

        vct = self.dag._build_volume_claim_templates()
        if vct:
            setattr(spec, "volume_claim_templates", vct)

        pcvs = self.dag._build_persistent_volume_claims()
        if pcvs:
            setattr(spec, "volumes", pcvs)

        if self.exit_task is not None:
            setattr(spec, "on_exit", self.exit_task)

        return spec

    def build(self) -> IoArgoprojWorkflowV1alpha1Workflow:
        """Builds the workflow core representation"""
        return IoArgoprojWorkflowV1alpha1Workflow(metadata=self._build_metadata(), spec=self._build_spec())

    def __enter__(self) -> "Workflow":
        """Enter the context of the workflow.

        Note that this creates a DAG if one is not specified. This supports using `with Workflow(...)`.
        """
        self.in_context = True
        if self.dag:
            raise ValueError("DAG already set for workflow")
        self.dag = DAG(name=self.name)
        hera.dag_context.enter(self.dag)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Leave the context of the workflow.

        This supports using `with Workflow(...)`.
        """
        self.in_context = False
        hera.dag_context.exit()

    def add_task(self, t: Task) -> "Workflow":
        """Add a task to the workflow"""
        add_task(self, t)
        return self

    def add_tasks(self, *ts: Task) -> "Workflow":
        """Add a collection of tasks to the workflow"""
        add_tasks(self, *ts)
        return self

    def create(self) -> "Workflow":
        """Creates the workflow"""
        assert self.dag
        if self.in_context:
            raise ValueError("Cannot invoke `create` when using a Hera context")

        self.service.create_workflow(self.build())
        return self

    def on_exit(self, other: Union[Task, DAG]) -> None:
        """Add a task or a DAG to execute upon workflow exit"""
        if isinstance(other, Task):
            self.exit_task = other.name
            other.is_exit_task = True
        else:
            # If the exit task is a DAG, we need to propagate the DAG and its
            # templates by instantiating a task within the current context.
            # The name will never be used; it's only present because the
            # field is mandatory.
            t = Task("temp-name-for-hera-exit-dag", dag=other)
            t.is_exit_task = True
            self.exit_task = other.name

    def delete(self) -> Tuple[object, int, dict]:
        """Deletes the workflow"""
        return self.service.delete(self.name)

    def get_parameter(self, name: str) -> Parameter:
        """Assembles the specified parameter name into a parameter specification"""
        if self.parameters is None or next((p for p in self.parameters if p.name == name), None) is None:
            raise KeyError("`{name}` not in workflow parameters")
        return Parameter(name, value=f"{{{{workflow.parameters.{name}}}}}")
