# PowerShell is test-only: it is deliberately absent from the quickalign runtime image.
ARG QUICKALIGN_TEST_IMAGE=quickalign:tools
FROM mcr.microsoft.com/powershell@sha256:7ab5bd5ca6f95a3351fa0c6a1205237d57048c94542355aab55519a0861a9b25 AS powershell
FROM ${QUICKALIGN_TEST_IMAGE}

COPY --from=powershell /opt/microsoft/powershell/7 /opt/microsoft/powershell/7
ENV PATH="/opt/microsoft/powershell/7:${PATH}" \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1

ENTRYPOINT []
CMD ["pytest"]
