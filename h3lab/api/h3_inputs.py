"""Public H3 request contract; historical run records stay in GenerationConfig."""
from typing import Annotated, Literal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from h3lab.domain.config import GenerationConfig

class References(BaseModel):
    model_config = ConfigDict(extra="forbid")
    images: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    video_audios: list[str] = Field(default_factory=list)
    audios: list[str] = Field(default_factory=list)

class Guide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame: int = 0
    image: str = ""
    video: str = ""
    audio: str = ""

class H3Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: Literal["speed", "quality", "quality_pece", "motion"] = "speed"
    prompt: str
    width: Annotated[int, Field(gt=0)] = 1344
    height: Annotated[int, Field(gt=0)] = 768
    frames: Annotated[int, Field(gt=0)] = 175
    seed: Annotated[int, Field(ge=0, le=2**53-1)] = 42
    references: References = Field(default_factory=References)
    guides: list[Guide] = Field(default_factory=list)
    first_frame: str = ""
    last_frame: str = ""
    ref_image_size: Literal["match", "max"] = "match"
    final_audio: str = ""
    experiment: dict[str, Any] = Field(default_factory=dict)

    def to_config(self) -> GenerationConfig:
        data = self.model_dump(exclude={"references", "guides", "final_audio"})
        return GenerationConfig(**data,
            diffusion_model="minimax-h3/minimax_h3_fastvideo_vsa_datafree_1300step_4step_int8_convrot.safetensors",
            sampler={"speed": "euler", "quality": "res_multistep", "quality_pece": "sa_solver_pece", "motion": "res_multistep"}[self.preset],
            scheduler="beta57" if self.preset == "quality_pece" else "simple",
            steps=4,
            mp=self.width * self.height / 1_000_000, duration_s=self.frames / 24,
            aspect_ratio=f"{self.width}:{self.height}", cache_enabled=False, cache="none", sol_attn=False,

            ref_images=self.references.images, ref_videos=self.references.videos,
            ref_video_audios=self.references.video_audios, ref_audios=self.references.audios,
            widgets={"guides": [guide.model_dump(exclude_defaults=True) for guide in self.guides], "final_audio": self.final_audio})
