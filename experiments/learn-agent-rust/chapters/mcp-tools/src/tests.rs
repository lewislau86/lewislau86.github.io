use crate::{
    adapter::{Approval, Entry, Invocation, Registry, alias, allowed},
    schema,
};
use serde_json::json;

#[test]
fn aliases_keep_distinct_server_identities() {
    assert_ne!(alias("a", "read_note"), alias("b", "read_note"));
    assert_eq!(alias("a__b", "read"), Err("unsupported_name"));
}
#[test]
fn unsupported_remote_names_are_rejected_without_rewriting() {
    for name in ["", "read.note", "a/b", "a b"] {
        assert!(alias("notes", name).is_err());
    }
    assert!(alias("notes", &"x".repeat(41)).is_err());
}
#[test]
fn references_and_combinators_are_not_silently_ignored() {
    let mut schema = schema::schema("path");
    schema["$ref"] = json!("https://invalid.example");
    assert_eq!(schema::admit(&schema), Err("unsupported_schema"));
    let mut schema = schema::schema("path");
    schema["allOf"] = json!([]);
    assert!(schema::admit(&schema).is_err());
}
#[test]
fn required_and_additional_fields_are_checked() {
    let schema = schema::schema("path");
    for args in [
        json!({}),
        json!({"path":4}),
        json!({"path":"x","extra":"y"}),
        json!([]),
    ] {
        assert_eq!(schema::validate(&schema, &args), Err("invalid_arguments"));
    }
}
#[test]
fn max_length_counts_unicode_characters() {
    let schema = schema::schema("text");
    assert!(schema::validate(&schema, &json!({"text":"诗".repeat(256)})).is_ok());
    assert!(schema::validate(&schema, &json!({"text":"诗".repeat(257)})).is_err());
}
#[test]
fn approval_binds_call_name_id_and_arguments() {
    let entry = Entry {
        server: Some("notes".into()),
        remote: "append_note".into(),
        input_schema: schema::schema("text"),
        description: "write".into(),
    };
    let original = Invocation {
        call_id: "1".into(),
        name: "mcp_notes__append_note".into(),
        arguments: json!({"text":"a"}),
    };
    let approval = Approval(original.clone());
    assert!(allowed(&entry, &original, Some(&approval)).is_ok());
    for changed in [
        Invocation {
            call_id: "2".into(),
            ..original.clone()
        },
        Invocation {
            name: "mcp_other__append_note".into(),
            ..original.clone()
        },
        Invocation {
            arguments: json!({"text":"b"}),
            ..original.clone()
        },
    ] {
        assert_eq!(
            allowed(&entry, &changed, Some(&approval)),
            Err("approval_required")
        );
    }
}
#[test]
fn local_and_remote_definitions_share_the_function_contract() {
    let registry = Registry::local();
    let definitions = registry.definitions();
    assert_eq!(definitions[0]["type"], "function");
    assert_eq!(
        definitions[0]["function"]["parameters"],
        schema::schema("path")
    );
}
#[test]
fn invalidation_removes_only_the_selected_server() {
    let mut registry = Registry::local();
    for server in ["a", "b"] {
        registry.0.insert(
            alias(server, "read").unwrap(),
            Entry {
                server: Some(server.into()),
                remote: "read".into(),
                input_schema: schema::schema("path"),
                description: "read".into(),
            },
        );
    }
    registry.invalidate("a");
    assert_eq!(registry.0.len(), 2);
    assert!(registry.0.contains_key("mcp_b__read"));
}
