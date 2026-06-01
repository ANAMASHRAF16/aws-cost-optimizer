"""CloudFormation template structural tests.

Verifies that template_fixed.yaml satisfies the four Activity 4 requirements
(auto-scaling, right-sized instance family, lifecycle hooks, cost tags)
plus a few cost-saving bonuses (gp3 storage, scaling policies).

The tests parse the YAML with a custom loader that handles CloudFormation's
short-form intrinsic functions (!Ref, !GetAtt, !Sub, etc.) without
evaluating them. We then walk the Resources dict and assert structural
properties - no AWS account or live stack needed.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
BROKEN = ROOT / "template_broken.yaml"
FIXED = ROOT / "template_fixed.yaml"


# ---------- CloudFormation YAML loader (handles !Ref, !GetAtt, etc.) ----------

class CfnTag:
    """Stand-in for an unevaluated CloudFormation intrinsic function."""
    def __init__(self, tag: str, value):
        self.tag = tag
        self.value = value

    def __repr__(self):
        return f"!{self.tag}({self.value!r})"


def _cfn_constructor(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node)
    else:
        value = None
    return CfnTag(tag_suffix, value)


class CfnSafeLoader(yaml.SafeLoader):
    pass


# Register handlers for every CloudFormation short-form intrinsic
for tag in ("Ref", "GetAtt", "Sub", "Join", "Select", "Split", "FindInMap",
            "If", "Equals", "Not", "And", "Or", "Base64", "Cidr", "ImportValue",
            "GetAZs", "Transform", "Condition"):
    CfnSafeLoader.add_constructor(f"!{tag}", lambda loader, node, t=tag: _cfn_constructor(loader, t, node))


def _load_template(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=CfnSafeLoader)


@pytest.fixture(scope="module")
def fixed_template() -> dict:
    return _load_template(FIXED)


@pytest.fixture(scope="module")
def fixed_resources(fixed_template) -> dict:
    return fixed_template["Resources"]


def _resources_of_type(resources: dict, type_name: str) -> dict:
    """Return {logical_id: resource_dict} for every resource of a given Type."""
    return {lid: r for lid, r in resources.items() if r.get("Type") == type_name}


# ---------- 1. Right-sized instance family ----------

def test_no_t2_instance_family_in_launch_template(fixed_resources):
    """t2.* is older generation - should be replaced with t3.* (cheaper + better burst)."""
    lts = _resources_of_type(fixed_resources, "AWS::EC2::LaunchTemplate")
    assert lts, "Expected at least one LaunchTemplate in the fixed template"
    for lid, lt in lts.items():
        instance_type = lt["Properties"]["LaunchTemplateData"]["InstanceType"]
        assert not instance_type.startswith("t2."), (
            f"{lid} uses {instance_type}; t2.* is older generation - migrate to t3.*"
        )


def test_no_oversized_xlarge_in_launch_template(fixed_resources):
    """A simple web app does NOT need 2xlarge or larger."""
    lts = _resources_of_type(fixed_resources, "AWS::EC2::LaunchTemplate")
    for lid, lt in lts.items():
        instance_type = lt["Properties"]["LaunchTemplateData"]["InstanceType"]
        assert "2xlarge" not in instance_type and "4xlarge" not in instance_type, (
            f"{lid} uses {instance_type}; oversized for a simple web app"
        )


def test_no_individual_ec2_instances(fixed_resources):
    """The fix should use Auto Scaling Group, not hardcoded EC2 instances."""
    instances = _resources_of_type(fixed_resources, "AWS::EC2::Instance")
    assert not instances, (
        f"Found hardcoded EC2 instances {list(instances.keys())} in fixed template - "
        f"these should be replaced with an Auto Scaling Group"
    )


# ---------- 2. Auto-scaling group ----------

def test_autoscaling_group_present(fixed_resources):
    asgs = _resources_of_type(fixed_resources, "AWS::AutoScaling::AutoScalingGroup")
    assert asgs, "Expected an Auto Scaling Group in the fixed template"


def test_autoscaling_min_size_at_least_one(fixed_resources):
    asgs = _resources_of_type(fixed_resources, "AWS::AutoScaling::AutoScalingGroup")
    for lid, asg in asgs.items():
        min_size = int(asg["Properties"]["MinSize"])
        assert min_size >= 1, f"{lid} MinSize is {min_size}; should be >= 1"


def test_autoscaling_can_scale_up(fixed_resources):
    """MaxSize must be greater than MinSize for the ASG to actually scale."""
    asgs = _resources_of_type(fixed_resources, "AWS::AutoScaling::AutoScalingGroup")
    for lid, asg in asgs.items():
        min_size = int(asg["Properties"]["MinSize"])
        max_size = int(asg["Properties"]["MaxSize"])
        assert max_size > min_size, (
            f"{lid} has MinSize={min_size}, MaxSize={max_size}; "
            f"ASG can't scale up if MaxSize is not greater"
        )


def test_scaling_policy_present(fixed_resources):
    policies = _resources_of_type(fixed_resources, "AWS::AutoScaling::ScalingPolicy")
    assert policies, (
        "Expected at least one ScalingPolicy - an ASG without one can't actually scale up "
        "on CPU/traffic; you'd have to scale manually"
    )


# ---------- 3. Lifecycle hooks ----------

def test_lifecycle_hooks_configured(fixed_resources):
    """Lifecycle hooks let instances drain connections gracefully on termination."""
    asgs = _resources_of_type(fixed_resources, "AWS::AutoScaling::AutoScalingGroup")
    for lid, asg in asgs.items():
        hooks = asg["Properties"].get("LifecycleHookSpecificationList")
        assert hooks, (
            f"{lid} has no LifecycleHookSpecificationList; instances are killed abruptly "
            f"on scale-down, dropping in-flight requests"
        )
        # Verify there's at least one termination hook
        transitions = [h.get("LifecycleTransition") for h in hooks]
        assert any("TERMINATING" in str(t) for t in transitions), (
            f"{lid} has lifecycle hooks but none for EC2_INSTANCE_TERMINATING - "
            f"the graceful-shutdown path isn't covered"
        )


# ---------- 4. Cost tags ----------

REQUIRED_TAG_KEYS = {"Project", "Environment"}


def _tag_keys(tags) -> set:
    """Pull the Key field out of a CloudFormation Tags list."""
    if not tags:
        return set()
    keys = set()
    for tag in tags:
        key = tag.get("Key")
        # Tag key may be a string or a CloudFormation ref - we only care about the literal name
        if isinstance(key, str):
            keys.add(key)
        elif isinstance(key, CfnTag):
            keys.add(str(key))
    return keys


def test_launch_template_propagates_tags_to_instances(fixed_resources):
    """The Launch Template must tag every instance it launches."""
    lts = _resources_of_type(fixed_resources, "AWS::EC2::LaunchTemplate")
    for lid, lt in lts.items():
        tag_specs = lt["Properties"]["LaunchTemplateData"].get("TagSpecifications") or []
        instance_tag_specs = [ts for ts in tag_specs if ts.get("ResourceType") == "instance"]
        assert instance_tag_specs, (
            f"{lid} TagSpecifications has no entry for ResourceType=instance; "
            f"launched EC2 instances will be untagged"
        )
        for ts in instance_tag_specs:
            keys = _tag_keys(ts.get("Tags", []))
            missing = REQUIRED_TAG_KEYS - keys
            assert not missing, (
                f"{lid} instance tags missing required cost-tracking keys: {missing}"
            )


def test_autoscaling_group_tags_propagate_at_launch(fixed_resources):
    """ASG-level tags should propagate to each instance via PropagateAtLaunch=true."""
    asgs = _resources_of_type(fixed_resources, "AWS::AutoScaling::AutoScalingGroup")
    for lid, asg in asgs.items():
        tags = asg["Properties"].get("Tags") or []
        cost_tag_propagating = [
            t for t in tags
            if t.get("Key") in REQUIRED_TAG_KEYS and t.get("PropagateAtLaunch") is True
        ]
        assert cost_tag_propagating, (
            f"{lid} should have at least one cost tag (Project/Environment) with "
            f"PropagateAtLaunch=true; otherwise tags only live on the ASG itself"
        )


def test_load_balancer_has_cost_tags(fixed_resources):
    lbs = _resources_of_type(fixed_resources, "AWS::ElasticLoadBalancingV2::LoadBalancer")
    for lid, lb in lbs.items():
        keys = _tag_keys(lb["Properties"].get("Tags", []))
        missing = REQUIRED_TAG_KEYS - keys
        assert not missing, f"{lid} missing cost tag keys: {missing}"


# ---------- 5. Storage right-sizing (cost bonus) ----------

def test_launch_template_uses_gp3_not_gp2(fixed_resources):
    """gp3 is ~20% cheaper than gp2 and gives better baseline IOPS."""
    lts = _resources_of_type(fixed_resources, "AWS::EC2::LaunchTemplate")
    for lid, lt in lts.items():
        mappings = lt["Properties"]["LaunchTemplateData"].get("BlockDeviceMappings", [])
        for m in mappings:
            ebs = m.get("Ebs", {})
            volume_type = ebs.get("VolumeType")
            if volume_type is not None:
                assert volume_type != "gp2", (
                    f"{lid} uses gp2 EBS volume type; gp3 is cheaper + faster"
                )


def test_launch_template_volume_size_reasonable(fixed_resources):
    """100GB+ root volumes are usually waste for stateless web servers."""
    lts = _resources_of_type(fixed_resources, "AWS::EC2::LaunchTemplate")
    for lid, lt in lts.items():
        mappings = lt["Properties"]["LaunchTemplateData"].get("BlockDeviceMappings", [])
        for m in mappings:
            ebs = m.get("Ebs", {})
            size = ebs.get("VolumeSize")
            if size is not None:
                assert int(size) <= 50, (
                    f"{lid} EBS VolumeSize is {size}GB; stateless web servers rarely "
                    f"need more than 20-30GB"
                )


# ---------- 6. Broken template still demonstrates the anti-patterns ----------

def test_broken_template_has_oversized_instances():
    """Sanity check that the baseline still shows what we're fixing."""
    broken = _load_template(BROKEN)
    instances = _resources_of_type(broken["Resources"], "AWS::EC2::Instance")
    assert instances, "Broken template should have hardcoded EC2 instances"
    for lid, inst in instances.items():
        t = inst["Properties"]["InstanceType"]
        assert t.startswith("t2.") or "2xlarge" in t or "4xlarge" in t, (
            f"Broken template's {lid} ({t}) should demonstrate the oversize anti-pattern"
        )


def test_broken_template_has_no_autoscaling():
    broken = _load_template(BROKEN)
    asgs = _resources_of_type(broken["Resources"], "AWS::AutoScaling::AutoScalingGroup")
    assert not asgs, "Broken template should not have auto-scaling (that's the fix)"
