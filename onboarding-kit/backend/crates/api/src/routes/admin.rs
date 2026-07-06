//! Admin endpoints (§7): tenant-wide CRUD for branches, users, and products.
//! Every handler is admin-only via the `RequireAdmin` guard and tenant-scoped.

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::routing::{get, patch};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use onboardkit_core::Role;
use onboardkit_db::users::NewUser;
use onboardkit_db::{Branch, Product, User, branches, products, users};
use onboardkit_integrations::{Phone, password};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use uuid::Uuid;

use crate::auth::RequireAdmin;
use crate::error::{AppError, AppResult};
use crate::state::AppState;

/// Translate a unique-constraint violation into a friendly 409.
fn conflict_on_unique(e: sqlx::Error, msg: &str) -> AppError {
    match &e {
        sqlx::Error::Database(db) if db.is_unique_violation() => AppError::Conflict(msg.to_owned()),
        _ => AppError::from(e),
    }
}

// ---- Overview -------------------------------------------------------------

#[derive(Serialize, ToSchema)]
pub(crate) struct AdminOverview {
    tenant_id: Uuid,
    branches: i64,
    users: i64,
    products: i64,
}

#[utoipa::path(
    get,
    path = "/api/v1/admin/overview",
    tag = "admin",
    security(("bearer_auth" = [])),
    responses((status = 200, description = "Tenant resource counts", body = AdminOverview)),
)]
pub(crate) async fn overview(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
) -> AppResult<Json<AdminOverview>> {
    let branches = i64::try_from(branches::list(&state.pool, user.tenant_id()).await?.len())
        .unwrap_or(i64::MAX);
    let users =
        i64::try_from(users::list(&state.pool, user.tenant_id()).await?.len()).unwrap_or(i64::MAX);
    let products = i64::try_from(products::list(&state.pool, user.tenant_id()).await?.len())
        .unwrap_or(i64::MAX);
    Ok(Json(AdminOverview {
        tenant_id: user.tenant_id(),
        branches,
        users,
        products,
    }))
}

// ---- Branches -------------------------------------------------------------

#[derive(Serialize, ToSchema)]
pub(crate) struct BranchDto {
    id: Uuid,
    name: String,
    code: String,
    created_at: DateTime<Utc>,
}

impl From<Branch> for BranchDto {
    fn from(b: Branch) -> Self {
        Self {
            id: b.id,
            name: b.name,
            code: b.code,
            created_at: b.created_at,
        }
    }
}

#[derive(Deserialize, ToSchema)]
pub(crate) struct CreateBranch {
    name: String,
    code: String,
}

#[derive(Deserialize, ToSchema)]
pub(crate) struct UpdateBranch {
    name: Option<String>,
    code: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/branches",
    tag = "admin",
    security(("bearer_auth" = [])),
    responses((status = 200, description = "All branches in the tenant", body = Vec<BranchDto>)),
)]
pub(crate) async fn list_branches(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
) -> AppResult<Json<Vec<BranchDto>>> {
    let rows = branches::list(&state.pool, user.tenant_id()).await?;
    Ok(Json(rows.into_iter().map(BranchDto::from).collect()))
}

#[utoipa::path(
    post,
    path = "/api/v1/branches",
    tag = "admin",
    security(("bearer_auth" = [])),
    request_body = CreateBranch,
    responses(
        (status = 201, description = "Branch created", body = BranchDto),
        (status = 409, description = "Branch code already exists"),
        (status = 422, description = "Name and code required"),
    ),
)]
pub(crate) async fn create_branch(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Json(req): Json<CreateBranch>,
) -> AppResult<(StatusCode, Json<BranchDto>)> {
    let name = req.name.trim();
    let code = req.code.trim();
    if name.is_empty() || code.is_empty() {
        return Err(AppError::Validation(
            "Branch name and code are required.".to_owned(),
        ));
    }
    let branch = branches::create(&state.pool, user.tenant_id(), name, code)
        .await
        .map_err(|e| conflict_on_unique(e, "A branch with that code already exists."))?;
    Ok((StatusCode::CREATED, Json(branch.into())))
}

#[utoipa::path(
    patch,
    path = "/api/v1/branches/{id}",
    tag = "admin",
    security(("bearer_auth" = [])),
    params(("id" = Uuid, Path, description = "Branch id")),
    request_body = UpdateBranch,
    responses(
        (status = 200, description = "Branch updated", body = BranchDto),
        (status = 404, description = "Branch not found"),
        (status = 409, description = "Branch code already exists"),
    ),
)]
pub(crate) async fn update_branch(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Path(id): Path<Uuid>,
    Json(req): Json<UpdateBranch>,
) -> AppResult<Json<BranchDto>> {
    let branch = branches::update(
        &state.pool,
        user.tenant_id(),
        id,
        req.name.as_deref(),
        req.code.as_deref(),
    )
    .await
    .map_err(|e| conflict_on_unique(e, "A branch with that code already exists."))?
    .ok_or(AppError::NotFound)?;
    Ok(Json(branch.into()))
}

// ---- Products -------------------------------------------------------------

#[derive(Serialize, ToSchema)]
pub(crate) struct ProductDto {
    id: Uuid,
    code: String,
    name: String,
    is_active: bool,
    created_at: DateTime<Utc>,
}

impl From<Product> for ProductDto {
    fn from(p: Product) -> Self {
        Self {
            id: p.id,
            code: p.code,
            name: p.name,
            is_active: p.is_active,
            created_at: p.created_at,
        }
    }
}

#[derive(Deserialize, ToSchema)]
pub(crate) struct CreateProduct {
    code: String,
    name: String,
}

#[derive(Deserialize, ToSchema)]
pub(crate) struct UpdateProduct {
    name: Option<String>,
    is_active: Option<bool>,
}

#[utoipa::path(
    get,
    path = "/api/v1/products",
    tag = "admin",
    security(("bearer_auth" = [])),
    responses((status = 200, description = "All products in the tenant", body = Vec<ProductDto>)),
)]
pub(crate) async fn list_products(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
) -> AppResult<Json<Vec<ProductDto>>> {
    let rows = products::list(&state.pool, user.tenant_id()).await?;
    Ok(Json(rows.into_iter().map(ProductDto::from).collect()))
}

#[utoipa::path(
    post,
    path = "/api/v1/products",
    tag = "admin",
    security(("bearer_auth" = [])),
    request_body = CreateProduct,
    responses(
        (status = 201, description = "Product created", body = ProductDto),
        (status = 409, description = "Product code already exists"),
        (status = 422, description = "Code and name required"),
    ),
)]
pub(crate) async fn create_product(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Json(req): Json<CreateProduct>,
) -> AppResult<(StatusCode, Json<ProductDto>)> {
    let code = req.code.trim();
    let name = req.name.trim();
    if code.is_empty() || name.is_empty() {
        return Err(AppError::Validation(
            "Product code and name are required.".to_owned(),
        ));
    }
    let product = products::create(&state.pool, user.tenant_id(), code, name)
        .await
        .map_err(|e| conflict_on_unique(e, "A product with that code already exists."))?;
    Ok((StatusCode::CREATED, Json(product.into())))
}

#[utoipa::path(
    patch,
    path = "/api/v1/products/{id}",
    tag = "admin",
    security(("bearer_auth" = [])),
    params(("id" = Uuid, Path, description = "Product id")),
    request_body = UpdateProduct,
    responses(
        (status = 200, description = "Product updated", body = ProductDto),
        (status = 404, description = "Product not found"),
    ),
)]
pub(crate) async fn update_product(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Path(id): Path<Uuid>,
    Json(req): Json<UpdateProduct>,
) -> AppResult<Json<ProductDto>> {
    let product = products::update(
        &state.pool,
        user.tenant_id(),
        id,
        req.name.as_deref(),
        req.is_active,
    )
    .await?
    .ok_or(AppError::NotFound)?;
    Ok(Json(product.into()))
}

// ---- Users ----------------------------------------------------------------

#[derive(Serialize, ToSchema)]
pub(crate) struct UserDto {
    id: Uuid,
    branch_id: Option<Uuid>,
    full_name: String,
    phone: String,
    email: String,
    #[schema(value_type = String)]
    role: Role,
    is_active: bool,
    created_at: DateTime<Utc>,
}

impl From<User> for UserDto {
    fn from(u: User) -> Self {
        Self {
            id: u.id,
            branch_id: u.branch_id,
            full_name: u.full_name,
            phone: u.phone,
            email: u.email,
            role: u.role,
            is_active: u.is_active,
            created_at: u.created_at,
        }
    }
}

#[derive(Deserialize, ToSchema)]
pub(crate) struct CreateUser {
    branch_id: Option<Uuid>,
    full_name: String,
    phone: String,
    email: String,
    password: String,
    #[schema(value_type = String)]
    role: Role,
}

#[derive(Deserialize, ToSchema)]
pub(crate) struct UpdateUser {
    branch_id: Option<Uuid>,
    is_active: Option<bool>,
}

#[utoipa::path(
    get,
    path = "/api/v1/users",
    tag = "admin",
    security(("bearer_auth" = [])),
    responses((status = 200, description = "All users in the tenant", body = Vec<UserDto>)),
)]
pub(crate) async fn list_users(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
) -> AppResult<Json<Vec<UserDto>>> {
    let rows = users::list(&state.pool, user.tenant_id()).await?;
    Ok(Json(rows.into_iter().map(UserDto::from).collect()))
}

#[utoipa::path(
    post,
    path = "/api/v1/users",
    tag = "admin",
    security(("bearer_auth" = [])),
    request_body = CreateUser,
    responses(
        (status = 201, description = "User created", body = UserDto),
        (status = 409, description = "Email already exists"),
        (status = 422, description = "Invalid name, password, branch, or phone"),
    ),
)]
pub(crate) async fn create_user(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Json(req): Json<CreateUser>,
) -> AppResult<(StatusCode, Json<UserDto>)> {
    let full_name = req.full_name.trim();
    if full_name.is_empty() {
        return Err(AppError::Validation("A full name is required.".to_owned()));
    }
    if req.password.len() < 8 {
        return Err(AppError::Validation(
            "Password must be at least 8 characters.".to_owned(),
        ));
    }
    // Non-admins must belong to a branch; admins are tenant-wide (§5).
    if req.role != Role::Admin && req.branch_id.is_none() {
        return Err(AppError::Validation(
            "Agents and reviewers must be assigned to a branch.".to_owned(),
        ));
    }
    let phone = Phone::parse(req.phone.trim())
        .map_err(|_| AppError::Validation("Invalid phone number.".to_owned()))?;
    let password_hash = password::hash(&req.password).map_err(|e| AppError::Internal(e.into()))?;

    let new = NewUser {
        branch_id: req.branch_id,
        full_name: full_name.to_owned(),
        phone: phone.as_str().to_owned(),
        email: req.email.trim().to_lowercase(),
        password_hash,
        role: req.role,
    };
    let id = users::create(&state.pool, user.tenant_id(), &new)
        .await
        .map_err(|e| conflict_on_unique(e, "A user with that email already exists."))?;

    let created = users::find_by_id(&state.pool, id)
        .await?
        .ok_or(AppError::NotFound)?;
    tracing::info!(user_id = %id, role = created.role.as_str(), "admin created user");
    Ok((StatusCode::CREATED, Json(created.into())))
}

#[utoipa::path(
    patch,
    path = "/api/v1/users/{id}",
    tag = "admin",
    security(("bearer_auth" = [])),
    params(("id" = Uuid, Path, description = "User id")),
    request_body = UpdateUser,
    responses(
        (status = 200, description = "User updated", body = UserDto),
        (status = 404, description = "User not found"),
    ),
)]
pub(crate) async fn update_user(
    State(state): State<AppState>,
    RequireAdmin(user): RequireAdmin,
    Path(id): Path<Uuid>,
    Json(req): Json<UpdateUser>,
) -> AppResult<Json<UserDto>> {
    let updated = users::update(
        &state.pool,
        user.tenant_id(),
        id,
        req.branch_id,
        req.is_active,
    )
    .await?;
    if !updated {
        return Err(AppError::NotFound);
    }
    let u = users::find_by_id(&state.pool, id)
        .await?
        .ok_or(AppError::NotFound)?;
    Ok(Json(u.into()))
}

/// Routes owned by this module.
pub fn router() -> Router<AppState> {
    Router::new()
        .route("/admin/overview", get(overview))
        .route("/branches", get(list_branches).post(create_branch))
        .route("/branches/{id}", patch(update_branch))
        .route("/products", get(list_products).post(create_product))
        .route("/products/{id}", patch(update_product))
        .route("/users", get(list_users).post(create_user))
        .route("/users/{id}", patch(update_user))
}
