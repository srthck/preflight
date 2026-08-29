/**
 * ProfileClient — Demo Commerce Android analysis fixture.
 *
 * This file is a static-analysis fixture representing the Android client
 * that consumes the ProfileAPI. It is NOT a deployable Android application;
 * it models architectural relationships for PreFlight analysis.
 *
 * Dependency this fixture encodes
 * --------------------------------
 *   ProfileAPI  --API_CONSUMES-->  AndroidClient (ProfileClient)
 *
 * ProfileClient calls GET /profile/{userId} and uses the `phoneNumber`
 * field from the response — which originates from users.phone_number.
 *
 * A breaking change to users.phone_number (e.g. type change, removal,
 * rename) propagates through:
 *
 *   users.phone_number
 *     --DB_READ-->     UserService
 *     --HTTP_CALL-->   ProfileAPI
 *     --API_CONSUMES--> ProfileClient   <-- this file
 *
 * The explicit phoneNumber reference on line ~60 is intentional so that
 * Day 2+ static analysis can recognise the API_CONSUMES edge automatically.
 */

package com.democommerce.client

// ---------------------------------------------------------------------------
// Response model
// ---------------------------------------------------------------------------

/**
 * Represents the JSON response body of GET /profile/{userId}.
 *
 * [phoneNumber] originates from users.phone_number via UserService and
 * ProfileAPI. If that column changes, this field is affected.
 */
data class ProfileResponse(
    val userId: Int,
    val name: String,
    val email: String,
    val phoneNumber: String?   // Originates from users.phone_number
)

// ---------------------------------------------------------------------------
// API interface
// ---------------------------------------------------------------------------

/**
 * Retrofit-style interface for the ProfileAPI.
 * Route: GET /profile/{userId}
 *
 * Day 2+ static analysis will detect this annotation as an API_CONSUMES edge.
 */
interface ProfileApiService {
    @GET("/profile/{userId}")
    // suspend fun getProfile(             // suspend fun = coroutine-based call
    //     @Path("userId") userId: Int     // path parameter
    // ): ProfileResponse
    fun getProfile(userId: Int): ProfileResponse  // simplified for fixture
}

// ---------------------------------------------------------------------------
// ProfileClient
// ---------------------------------------------------------------------------

/**
 * Android client that fetches and displays user profile data.
 *
 * API_CONSUMES dependency: consumes ProfileAPI GET /profile/{userId}
 * and displays [ProfileResponse.phoneNumber] in the UI.
 */
class ProfileClient(
    private val apiService: ProfileApiService,
) {

    /**
     * Fetch the profile for [userId] from ProfileAPI.
     *
     * API_CONSUMES: GET /profile/{userId}
     *
     * The returned [ProfileResponse.phoneNumber] is displayed in the UI.
     * This creates the terminal dependency in the 3-hop chain:
     *   users.phone_number → UserService → ProfileAPI → ProfileClient
     */
    fun fetchProfile(userId: Int): ProfileResponse {
        // In production this is a coroutine-based network call.
        // Day 2 static analysis will detect the HTTP client call pattern.
        return apiService.getProfile(userId)
    }

    /**
     * Display the profile in the UI.
     *
     * Explicitly uses phoneNumber, establishing the terminal dependency
     * on users.phone_number through the entire chain.
     */
    fun displayProfile(userId: Int) {
        val profile = fetchProfile(userId)

        // phone_number dependency is explicit here.
        // A null phoneNumber means the field was removed or is unavailable —
        // this is the scenario PreFlight's rollback analysis will flag.
        val displayPhone = profile.phoneNumber ?: "(no phone on record)"

        println("Name:  ${profile.name}")
        println("Email: ${profile.email}")
        println("Phone: $displayPhone")   // users.phone_number consumer
    }
}
