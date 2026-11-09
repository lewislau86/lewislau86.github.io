use serde_json::{Value, json};

pub type Check<T> = Result<T, &'static str>;

pub fn schema(field: &str) -> Value {
    json!({"type":"object", "properties":{field:{"type":"string","maxLength":256}},
           "required":[field], "additionalProperties":false})
}

// region schema
// Deliberately bounded subset, not a general JSON Schema implementation.
pub fn admit(schema: &Value) -> Check<()> {
    let object = schema.as_object().ok_or("unsupported_schema")?;
    if object
        .keys()
        .any(|k| !["type", "properties", "required", "additionalProperties"].contains(&k.as_str()))
        || schema["type"] != "object"
        || schema["additionalProperties"] != false
    {
        return Err("unsupported_schema");
    }
    let properties = schema["properties"]
        .as_object()
        .ok_or("unsupported_schema")?;
    let required = schema["required"].as_array().ok_or("unsupported_schema")?;
    if properties.len() > 8 || required.len() != properties.len() {
        return Err("unsupported_schema");
    }
    let names: std::collections::BTreeSet<_> = required.iter().filter_map(Value::as_str).collect();
    if names.len() != required.len() || properties.keys().any(|key| !names.contains(key.as_str())) {
        return Err("unsupported_schema");
    }
    for value in properties.values() {
        let rule = value.as_object().ok_or("unsupported_schema")?;
        if rule
            .keys()
            .any(|k| !["type", "maxLength"].contains(&k.as_str()))
            || value["type"] != "string"
            || !matches!(value["maxLength"].as_u64(), Some(1..=1024))
        {
            return Err("unsupported_schema");
        }
    }
    Ok(())
}

pub fn validate(schema: &Value, arguments: &Value) -> Check<()> {
    admit(schema)?;
    let values = arguments.as_object().ok_or("invalid_arguments")?;
    let properties = schema["properties"]
        .as_object()
        .ok_or("unsupported_schema")?;
    if values.len() != properties.len() {
        return Err("invalid_arguments");
    }
    for (name, rule) in properties {
        let value = values
            .get(name)
            .and_then(Value::as_str)
            .ok_or("invalid_arguments")?;
        if value.chars().count() > rule["maxLength"].as_u64().unwrap_or(0) as usize {
            return Err("invalid_arguments");
        }
    }
    Ok(())
}
// endregion schema
