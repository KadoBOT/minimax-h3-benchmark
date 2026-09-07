from pathlib import Path
import json
import pytest
from h3lab.api.h3_inputs import H3Inputs
from tests.clean_workflow import build, editor, workflow, SCHEMAS
from h3lab.comfy.experiment import apply_experiment
from h3lab.domain.config import config_hash
from h3lab.domain.sweeps import SweepSpec, expand
from h3lab.domain.arena import ArenaRun, contested_differences, pool_key
from h3lab.domain.insights import axis_value, _seed_matched_key

ROOT = Path(__file__).resolve().parents[1]

def graph(preset='quality'):
    return editor.to_prompt(workflow(preset), SCHEMAS.__getitem__)

def config(**experiment):
    return H3Inputs(prompt='Rain on a neon street.', experiment=experiment).to_config()

@pytest.mark.parametrize('preset', ['speed','quality','quality_pece','motion'])
def test_recipe_is_unchanged_without_experiment(preset):
    source = graph(preset)
    assert apply_experiment(source,{}) == source

@pytest.mark.parametrize('preset', ['quality','quality_pece'])
def test_primary_sampler_and_steps_reach_primary_pass_only(preset):
    source = graph(preset)
    result = apply_experiment(source, {'sampler':'euler','scheduler':'beta','steps':9})
    sampler = result['116']['inputs']['sampler'][0]
    assert result[sampler]['inputs']['sampler_name'] == 'euler'
    assert result['114']['inputs']['steps'] == 9
    assert result['114']['inputs']['scheduler'] == 'beta'
    refine = result['141']['inputs']['sampler'][0]
    assert result[refine]['inputs']['sampler_name'] == 'res_multistep'
    assert source == graph(preset)

def test_lora_stack_preserves_order_strength_and_steps():
    result = apply_experiment(graph(), {'diffusion_model':'custom.safetensors','steps':13,
        'loras':[{'name':'a.safetensors','strength':0.35},{'name':'b.safetensors','strength':-0.2}]})
    assert result['104']['inputs']['unet_name'] == 'custom.safetensors'
    assert result['benchmark_lora_0']['inputs']['model'] == ['104',0]
    assert result['benchmark_lora_1']['inputs']['model'] == ['benchmark_lora_0',0]
    assert result['105']['inputs']['model'] == ['benchmark_lora_1',0]
    assert result['benchmark_lora_1']['inputs']['strength_model'] == -0.2
    assert result['114']['inputs']['steps'] == 13

def test_refinement_can_be_added_disabled_and_adjusted():
    result = apply_experiment(graph('speed'), {'refine_enabled':True,'refine_sampler':'heun','refine_sigmas':'0.2,0.1,0'})
    assert result['117']['inputs']['samples'] == ['benchmark_refine',0]
    assert result['benchmark_refine_sigmas']['inputs']['sigmas'] == '0.2,0.1,0'
    assert result['140']['class_type'] == 'H3SLAAttention'
    assert result['benchmark_refine_sampler']['inputs']['sampler_name'] == 'heun'
    result = apply_experiment(graph(), {'refine_enabled':False})
    assert result['117']['inputs']['samples'] == ['116',0]
    assert '141' not in result

def test_gguf_uses_its_loader():
    result = apply_experiment(graph(), {'diffusion_model':'model.gguf'})
    assert result['104']['class_type'] == 'UnetLoaderGGUF'
    assert 'weight_dtype' not in result['104']['inputs']

def test_advanced_node_inputs_are_applied_and_bad_node_is_reported():
    result = apply_experiment(graph(), {'node_inputs':{'106':{'selection.keep_percent':25}}})
    assert result['106']['inputs']['selection.keep_percent'] == 25
    with pytest.raises(ValueError, match='Unknown experiment node'):
        apply_experiment(graph(), {'node_inputs':{'missing':{'steps':8}}})

def test_sweeps_preserve_experiment_values_and_identity():
    configs = expand(SweepSpec(base=config(),axes=[{'field':'experiment.steps','values':[4,9]},
        {'field':'experiment.loras','values':[[{'name':'a','strength':0.2}],[{'name':'a','strength':0.8}]]}]))
    assert len({config_hash(c) for c in configs}) == 4
    assert [c.effective_steps for c in configs] == [4,4,9,9]
    assert configs[-1].experiment['loras'][0]['strength'] == 0.8

def test_sampling_experiments_share_arena_pool_but_have_distinct_axis():
    a,b = config(steps=4),config(steps=9)
    assert pool_key(a) == pool_key(b)
    assert [diff.field for diff in contested_differences(a,b)] == ['experiment.steps']
    assert axis_value(b,'experiment.steps') == '9'
    assert _seed_matched_key(a,'experiment.steps') == _seed_matched_key(b,'experiment.steps')

def test_reference_groups_and_timed_guides_remain_native():
    values = H3Inputs(prompt='A scene', references={'images':['a.png'],'videos':['a.mp4','b.mp4'],
        'video_audios':['','b.wav'],'audios':['voice.wav']}, guides=[{'frame':34,'video':'g.mp4','audio':'g.wav'}])
    from h3lab.comfy.studio import studio_inputs
    prepared = studio_inputs(values.to_config())
    assert prepared['references']['video_audios'] == ['','b.wav']
    assert prepared['guides'] == [{'frame':34,'video':'g.mp4','audio':'g.wav'}]
    assert prepared['width'] == 1344 and prepared['frames'] == 175

def test_preparation_resolves_folder_qualified_weights_with_duplicate_basenames():
    from h3lab.comfy.schema import Schemas
    from h3lab.comfy.studio import prepare_prompt
    cfg = config(sampler='res_multistep', steps=5, diffusion_model='minimax-h3/minimax_h3_fastvideo_vsa_datafree_1300step_4step_int8_convrot.safetensors')
    filename = cfg.diffusion_model.split('/')[-1]
    expected = 'previous_install\\minimax-h3\\' + filename
    schemas = Schemas({'UNETLoader': {'input': {'required': {'unet_name': [[expected, 'previous_install\\' + filename]]}}}})
    class Client:
        def prepare_studio(self, workflow, inputs):
            return {'workflow': graph('speed'), 'inputs': inputs}
    result = prepare_prompt(Client(), {}, cfg, schemas=schemas)
    assert result.prompt['104']['inputs']['unet_name'] == expected
    assert result.prompt['114']['inputs']['steps'] == 5


def test_motion_propagates_scene_inputs_without_overwriting_derope_nodes():
    request = H3Inputs(preset="motion", prompt="Run and turn", frames=90, seed=99,
                       references={"images": ["hero.png"]}, guides=[{"image": "start.png", "frame": 0}])
    assert request.to_config().sampler == "res_multistep"
    result = build(request.model_dump(exclude={"experiment"}))
    workflow = result["workflow"]
    assert workflow["200"]["class_type"] == "H3JerkOracle"
    assert workflow["200"]["inputs"]["length"] == 90
    assert workflow["207"]["inputs"]["noise_seed"] == 100
    assert workflow["209"]["inputs"]["prompt"] == "Run and turn"
    assert workflow["209"]["inputs"]["length"] == ["201", 2]
    ref = workflow["209"]["inputs"]["ref_images.ref_image_0"]
    assert workflow[ref[0]]["inputs"]["image"] == "hero.png"
    assert workflow[workflow["115"]["inputs"]["conditioning"][0]]["class_type"] == "MiniMaxH3AddGuide"
    assert workflow["119"]["inputs"]["images"] == ["216", 0]
    assert workflow["217"]["inputs"]["reference_mix"] == 1
    for node in apply_experiment(workflow, {"refine_enabled": False}).values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                assert value[0] not in ("140", "141")
