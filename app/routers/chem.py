from typing import List, Annotated, Union
from app.core.config import LWREG_CONFIG
from psycopg2.errors import UniqueViolation
from app.modules.cdkmodules import getCDKHOSECodes
from fastapi import APIRouter, HTTPException, Body, status, Query
from app.modules.rdkitmodules import getRDKitHOSECodes
from lwreg.utils import (
    initdb,
    bulk_register,
    query,
    retrieve,
    RegistrationFailureReasons,
)
from app import schemas
from rdkit import Chem
from io import BytesIO

router = APIRouter(
    prefix="/chem",
    tags=["chem"],
    dependencies=[],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "/health",
    tags=["healthcheck"],
    summary="Perform a Health Check on Chem Module",
    response_description="Returns HTTP Status Code 200 (OK)",
    status_code=status.HTTP_200_OK,
    response_model=schemas.HealthCheck,
    include_in_schema=False,
)
def get_health() -> schemas.HealthCheck:
    """
    ## Perform a Health Check
    Endpoint to perform a healthcheck on. This endpoint can primarily be used Docker
    to ensure a robust container orchestration and management is in place. Other
    services which rely on proper functioning of the API service will not deploy if this
    endpoint returns any other HTTP status code except 200 (OK).

    Returns:
        HealthCheck: Returns a JSON response with the health status
    """
    return schemas.HealthCheck(status="OK")


@router.post(
    "/init",
    tags=["chem"],
    summary="Initializes the registration database",
    response_description="Returns boolean indicating the success of the initialisation",
    status_code=status.HTTP_200_OK,
    response_model=Union[bool, None],
)
async def initialise_database(confirm: Annotated[bool, Body(embed=True)] = False):
    """
    ## Initializes the registration database

    NOTE: This call destroys any existing information in the registration database

    Arguments:

    confirm -- if set to False we immediately return
    """
    return initdb(config=LWREG_CONFIG, confirm=confirm)


@router.post(
    "/register",
    tags=["chem"],
    summary="Registers new molecules",
    response_description="Returns the new registry number(s) (molregno). If all entries are duplicates exception is raised",
    status_code=status.HTTP_200_OK,
    response_model=List[str | int],
)
async def register_compounds(
    data: Annotated[
        str,
        Body(embed=False, media_type="text/plain"),
    ] = "CCCC"
):
    """
    ## Registers new molecules, assuming it doesn't already exist,
    and returns the new registry number(s) (molregno). If all entries
    are duplicates exception is raised

    #### Only one of the molecule format objects should be provided

    molblock   -- MOL or SDF block
    smiles     -- smiles
    """
    try:
        if "$$$$" in data:
            molStream = BytesIO(data.encode("utf8"))
            mols = [m for m in Chem.ForwardSDMolSupplier(molStream)]
        else:
            smiles = data.splitlines()
            mols = [Chem.MolFromSmiles(smi) for smi in smiles]
        if len(mols) > 0:
            db_responses = bulk_register(mols=mols, config=LWREG_CONFIG)
            reg_responses = []
            ops_total_failure = True
            for res in db_responses:
                if res == RegistrationFailureReasons.PARSE_FAILURE:
                    reg_responses.append("PARSE_FAILURE")
                elif res == RegistrationFailureReasons.DUPLICATE:
                    reg_responses.append("DUPLICATE")
                else:
                    ops_total_failure = False
                    reg_responses.append(res)
            if ops_total_failure:
                raise
            else:
                return reg_responses
        else:
            raise
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail="Registration failed: ALL_DUPLICATE_ENTRIES " + e.message,
        )


@router.get(
    "/query",
    tags=["chem"],
    summary="Queries to see if a molecule has already been registered",
    response_model=List[int],
    response_description="Returns the corresponding registry numbers (molregnos)",
    status_code=status.HTTP_200_OK,
)
async def query_compounds(smi: str):
    """
    ## Queries to see if a molecule has already been registered

    Returns:
        Corresponding registry numbers (molregnos)
    """
    try:
        res = query(smiles=smi, config=LWREG_CONFIG)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error" + e.message,
        )


@router.post(
    "/retrieve",
    tags=["chem"],
    summary="Retrieves entries based on the list of ids provided",
    response_model=tuple(),
    response_description="Returns HTTP Status Code 200 (OK)",
    status_code=status.HTTP_200_OK,
)
async def retrieve_compounds(ids: List[int]):
    """
    ## Retrieves entries based on the ids provided

    Returns:
        Molecule data for one or more registry ids (molregnos).
        The return value is a tuple of (molregno, data, format) 3-tuples
    """
    try:
        res = retrieve(ids=ids, config=LWREG_CONFIG)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error" + e.message,
        )


@router.get(
    "/hosecode",
    tags=["chem"],
    summary="Generates HOSE codes of molecule",
    response_model=list[str],
    response_description="Returns an array of hose codes generated",
    status_code=status.HTTP_200_OK,
)
async def HOSE_Codes(
    smiles: Annotated[str, Query(examples=["CCCC1CC1"])],
    framework: Annotated[str, Query(enum=["cdk", "rdkit"])] = "cdk",
    spheres: Annotated[int, Query()] = 3,
    usestereo: Annotated[bool, Query()] = False,
) -> list[str]:
    """
    ## Generates HOSE codes for a given molecule
    Endpoint to generate HOSE codes based on for each atom in the givem molecule.

    Returns:
        HOSE Codes: An array of hose codes generated
    """
    try:
        if framework == "cdk":
            return await getCDKHOSECodes(smiles, spheres, usestereo)
        elif framework == "rdkit":
            return await getRDKitHOSECodes(smiles, spheres)
    except UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="Unique constraint violation. Molecule already exists.",
            headers={
                "X-Error": "Molecule already exists. Duplicate entries are not allowed"
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail="Error paring the structure " + e.message,
            headers={"X-Error": "RDKit molecule input parse error"},
        )
