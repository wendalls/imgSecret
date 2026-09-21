# Publish This Repository Anonymously

The local repository already uses the `main` branch.  Create an empty GitHub
repository under an account that does not reveal author identity, then run the
following commands from this directory:

```bash
git add .
git commit -m "Anonymous reproducibility package"
git remote add origin https://github.com/ANONYMOUS-OWNER/sarr-xvcs-reproducibility.git
git push -u origin main
```

Replace `ANONYMOUS-OWNER` with the anonymous account or organization name. Do not initialize
the remote repository with another README or license, because both are already
included here.

After publishing, place the anonymous URL in the manuscript availability
statement. Replace it with the public archival URL only after the review policy
permits de-anonymization.
