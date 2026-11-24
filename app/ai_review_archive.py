"""Publish paid images first, then atomically attach an optional QA report."""
import json
import os
import shutil
import zipfile


def attach_review(folder, review):
    """Replace only the report; preserve the original valid ZIP on failure.

    A concurrent downloader sees a complete old or new archive, never an
    in-place truncated ZIP. Stream already-compressed artwork to limit RAM.
    """
    archive=folder/"ai_posters.zip"
    temporary=folder/".reviewed.zip"
    try:
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(
                temporary,"w",compression=zipfile.ZIP_STORED) as target:
            for member in source.infolist():
                if member.filename=="poster_review.json":
                    continue
                with source.open(member) as inp,target.open(member.filename,"w") as out:
                    shutil.copyfileobj(inp,out,1024*1024)
            target.writestr("poster_review.json",json.dumps(review,ensure_ascii=False,indent=2))
        os.replace(temporary,archive)
        return True
    except (OSError,ValueError,zipfile.BadZipFile):
        return False
    finally:
        temporary.unlink(missing_ok=True)
