from pydantic import BaseModel, Field
from typing import Dict, Any, Annotated


RepoName = Annotated[
    str,
    Field(
        pattern=r"^[a-zA-Z0-9_-]+$",
        min_length=1,
        max_length=100
    )
]

class IngestRequest(BaseModel):

    repo_name: RepoName = Field(
        ...,
        description="Name of the repository",
        examples=["Conv2dLSTM"]
    )

    target_path: str = Field(
        ...,
        description="Absolute path to the repository",
        examples=["//home//akshat_ubuntu//project//local-code-graph//my_mock_test"]
    )


class JobStatusResponse(BaseModel):
    job_id: str = Field(
        ...,
        description="This UUID is returned by the request API, so that the job status can be checked with job polling API."
    )
    status: str = Field(
        ...,
        description="This returns the current status of the job, against the job_id."  # 'pending', 'processing', 'completed', 'failed'
    ) 
    message: str | None = None
    details: Dict[str, Any] | None = None