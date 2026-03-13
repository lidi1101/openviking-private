use crate::client::HttpClient;
use crate::error::Result;
use crate::output::{output_success, OutputFormat};

pub async fn add_resource(
    client: &HttpClient,
    path: &str,
    to: Option<String>,
    parent: Option<String>,
    reason: String,
    instruction: String,
    wait: bool,
    timeout: Option<f64>,
    strict: bool,
    ignore_dirs: Option<String>,
    include: Option<String>,
    exclude: Option<String>,
    directly_upload_media: bool,
    format: OutputFormat,
    compact: bool,
) -> Result<()> {
    let result = client
        .add_resource(
            path,
            to,
            parent,
            &reason,
            &instruction,
            wait,
            timeout,
            strict,
            ignore_dirs,
            include,
            exclude,
            directly_upload_media,
        )
        .await?;
    output_success(&result, format, compact);
    Ok(())
}

pub async fn add_skill(
    client: &HttpClient,
    data: &str,
    wait: bool,
    timeout: Option<f64>,
    format: OutputFormat,
    compact: bool,
) -> Result<()> {
    let result = client.add_skill(data, wait, timeout).await?;
    output_success(&result, format, compact);
    Ok(())
}

pub async fn build_index(
    client: &HttpClient,
    resource_uris: Vec<String>,
    wait: bool,
    timeout: Option<f64>,
    format: OutputFormat,
    compact: bool,
) -> Result<()> {
    let result = client.build_index(resource_uris, wait, timeout).await?;
    output_success(&result, format, compact);
    Ok(())
}

pub async fn summarize(
    client: &HttpClient,
    resource_uris: Vec<String>,
    wait: bool,
    timeout: Option<f64>,
    skip_vectorization: bool,
    format: OutputFormat,
    compact: bool,
) -> Result<()> {
    let result = client
        .summarize(resource_uris, wait, timeout, skip_vectorization)
        .await?;
    output_success(&result, format, compact);
    Ok(())
}
