/**
 * ProfileClient — Demo Commerce Android analysis fixture (remediated release).
 *
 * phoneNumber has been removed from the response model and is no longer
 * displayed. This, together with the remediated UserService and ProfileAPI,
 * removes users.phone_number from the dependency graph entirely.
 */

package com.democommerce.client

data class ProfileResponse(
    val userId: Int,
    val name: String,
    val email: String
)

interface ProfileApiService {
    @GET("/profile/{userId}")
    fun getProfile(userId: Int): ProfileResponse
}

class ProfileClient(
    private val apiService: ProfileApiService,
) {
    fun fetchProfile(userId: Int): ProfileResponse {
        return apiService.getProfile(userId)
    }

    fun displayProfile(userId: Int) {
        val profile = fetchProfile(userId)
        println("Name:  ${profile.name}")
        println("Email: ${profile.email}")
    }
}
