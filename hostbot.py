import base64
import asyncio
from dataclasses import dataclass
from typing import Optional

import os
import argparse
import logging

from hostbot.config import (
    EMBED_FOOTER_TEXT,
    EMBED_THUMBNAIL_URL,
    EMBED_REFRESH_INTERVAL,
    DISCORD_COHOST_ROLE_ID,
    DISCORD_OPS_ROLE_ID,
    OPS_ADMIN_USER_IDS,
    configure_logging,
    load_config_from_env,
    load_config_from_file,
)
from hostbot.storage import (
    get_zoom_name_from_file,
    load_host_command_message_id,
    load_room_number,
    save_host_command_message_id,
    save_room_number,
    save_zoom_name_to_file,
)
from hostbot.triggercmd import (
    send_host_cmd,
    send_next_track_cmd,
    send_reclaim_cmd,
    send_revoke_cmd,
    send_trigger_cmd,
    send_unmute_cmd,
)
from hostbot.dashboard import DashboardServer
import discord
from discord import app_commands
from discord.ext import commands

# Queue for outgoing TriggerCMD requests
request_queue: Optional[asyncio.Queue] = None
dashboard: Optional[DashboardServer] = None

# Runtime configuration values that admins can modify
embed_title = "WHAT IT MEAN TO SELF ASSIGN CO-HOST"
embed_body = (
    "1. Simply press the button below.\n"
    "2. If you haven't saved your Zoom name yet, "
    "you will see a popup form to save it.\n"
    "3. Make sure to use the same font and "
    "characters as your Zoom name.\n"
    "4. Your cam must be turned on, else you won't "
    "be assigned co-host."
)
embed_color = discord.Color.blue()
embed_thumbnail = EMBED_THUMBNAIL_URL
embed_footer = EMBED_FOOTER_TEXT

embed_refresh_interval = EMBED_REFRESH_INTERVAL
queue_delay = 10
room_number = load_room_number() or ""


@dataclass
class Request:
    """Data structure for queued TriggerCMD requests."""

    encoded_name: str


DISCORD_BOT_TOKEN = None
DISCORD_CHANNEL_ID = None
DISCORD_BOT_LOG = None


async def send_log_embed(
    bot: commands.Bot,
    description: str,
    *,
    title: Optional[str] = None,
    footer: Optional[str] = None,
) -> None:
    """Send an embed to the bot log channel.

    Parameters
    ----------
    bot:
        The bot instance used to fetch the log channel.
    description:
        The embed body text.
    title:
        Optional embed title.
    footer:
        Optional footer text.
    """

    channel = bot.get_channel(DISCORD_BOT_LOG)
    if channel:
        embed = discord.Embed(description=description, color=discord.Color.orange())
        if title:
            embed.title = title
        embed.set_footer(text=footer or EMBED_FOOTER_TEXT)
        await channel.send(embed=embed)


async def send_temporary_embed(
    interaction: discord.Interaction,
    embed: discord.Embed,
    *,
    delay: int = 5,
    ephemeral: bool = True,
) -> None:
    """Send an embed and delete it after ``delay`` seconds.

    Parameters
    ----------
    interaction:
        Interaction to respond to.
    embed:
        Embed object to send in the response.
    delay:
        Seconds to wait before deleting the message. Defaults to ``5``.
    ephemeral:
        Whether to send the message ephemerally. Defaults to ``True``.
    """

    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    await asyncio.sleep(delay)
    try:
        await interaction.delete_original_response()
    except Exception as exc:  # Message might already be deleted
        logging.debug("Failed to delete temporary embed: %s", exc)


async def queue_worker(bot: commands.Bot) -> None:
    """Process queued co-host requests."""

    while True:
        request: Request = await request_queue.get()
        try:
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, send_trigger_cmd, request.encoded_name)
            name = base64.b64decode(request.encoded_name).decode()
            if success:
                await send_log_embed(bot, f"Co-host has been assigned to {name}.")
            else:
                await send_log_embed(bot, f"Failed to send co-host trigger for {name}.")
        except Exception as exc:
            logging.error("Queue worker error: %s", exc)
        await asyncio.sleep(queue_delay)


# Discord bot view for host command controls
class HostCommandView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Self Assign Co-Host",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def self_assign_cohost(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            encoded_name = get_zoom_name_from_file(interaction.user.id)
            if encoded_name:
                await request_queue.put(Request(encoded_name))
                position = request_queue.qsize()
                await interaction.response.send_message(
                    f"Your co-host request has been queued. You are #{position} in line.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Please update your Zoom name first using 📋 Update Zoom Name",
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.response.send_message(f"Error assigning Co-Host: {e}", ephemeral=True)

    @discord.ui.button(
        label="Update Zoom Name",
        emoji="<:zoom:1081325108624371732>",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def update_zoom_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ZoomNameModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Operations",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Display admin tools to administrators or members with ``DISCORD_OPS_ROLE``."""

        allowed_role = None
        if interaction.guild and DISCORD_OPS_ROLE_ID:
            allowed_role = interaction.guild.get_role(DISCORD_OPS_ROLE_ID)

        has_role = allowed_role in interaction.user.roles if allowed_role else False
        is_hardcoded_ops = interaction.user.id in OPS_ADMIN_USER_IDS
        if not (
            interaction.guild
            and (interaction.user.guild_permissions.administrator or has_role or is_hardcoded_ops)
        ):
            await interaction.response.send_message(
                "You do not have permission to access admin tools.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Admin tools:", view=AdminToolsView(), ephemeral=True
        )

    @discord.ui.button(label="Unmute", emoji="🎙️", style=discord.ButtonStyle.secondary, row=1)
    async def unmute(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Ask for confirmation before sending the unmute command."""

        await interaction.response.send_message(
            "Confirm unmute?", ephemeral=True, view=ConfirmUnmuteView()
        )


class ConfirmUnmuteView(discord.ui.View):
    """View presenting Yes and Cancel buttons for unmute confirmation."""

    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Server will be unmuted in 8 seconds...", view=None
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, send_unmute_cmd)
        msg = interaction.message
        for i in range(7, 0, -1):
            await asyncio.sleep(1)
            await msg.edit(content=f"Server will be unmuted in {i} seconds...")
        await asyncio.sleep(1)
        await msg.edit(content="Unmute command sent.")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Unmute cancelled.", view=None)


# Admin tools view
class AdminToolsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Assign Co-Host",
        emoji="🤝",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def assign_cohost(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open a modal to manually assign co-host by Zoom name."""

        await interaction.response.send_modal(AssignCohostModal())

    @discord.ui.button(
        label="Assign Host",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def assign_host(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open a modal to manually assign host by Zoom name."""

        await interaction.response.send_modal(AssignHostModal())

    @discord.ui.button(
        label="Revoke Co-Host",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def revoke_cohost(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open a modal to revoke co-host by Zoom name."""

        await interaction.response.send_modal(RevokeCohostModal())

    @discord.ui.button(
        label="Enable Host Command",
        emoji="🟢",
        style=discord.ButtonStyle.secondary,
        row=3,
    )
    async def enable_host_command(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Allow specified roles to view the host channel and rename it."""

        if not interaction.guild:
            await interaction.response.send_message("Guild not found", ephemeral=True)
            return

        channel = interaction.guild.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("Channel not found", ephemeral=True)
            return

        roles = []
        if DISCORD_COHOST_ROLE_ID:
            role = interaction.guild.get_role(DISCORD_COHOST_ROLE_ID)
            if role:
                roles.append(role)

        if not roles:
            await interaction.response.send_message("Roles not configured", ephemeral=True)
            return

        for role in roles:
            overwrites = channel.overwrites_for(role)
            overwrites.view_channel = True
            await channel.set_permissions(role, overwrite=overwrites)

        await channel.edit(name="〔🟢〕hostbot")
        await interaction.response.send_message("Host command enabled", ephemeral=True)

    @discord.ui.button(
        label="Reclaim Host",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def reclaim_host(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Send a TriggerCMD command to reclaim host."""

        try:
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, send_reclaim_cmd)
            if success:
                await interaction.response.send_message("Reclaim host command sent", ephemeral=True)
            else:
                await interaction.response.send_message(
                    "Failed to send reclaim host command", ephemeral=True
                )
        except Exception as exc:
            await interaction.response.send_message(
                f"Error sending reclaim host command: {exc}", ephemeral=True
            )

    @discord.ui.button(
        label="Next Track",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def next_track(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Send a TriggerCMD command to skip to the next track."""

        try:
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, send_next_track_cmd)
            if success:
                await interaction.response.send_message("Next track command sent", ephemeral=True)
            else:
                await interaction.response.send_message(
                    "Failed to send next track command", ephemeral=True
                )
        except Exception as exc:
            await interaction.response.send_message(
                f"Error sending next track command: {exc}", ephemeral=True
            )

    @discord.ui.button(label="Room Started", style=discord.ButtonStyle.green, row=2)
    async def room_started(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Announce that the room has started."""

        if not room_number:
            await interaction.response.send_message("Room number not set.", ephemeral=True)
            return
        await interaction.channel.send(f"\N{LARGE GREEN CIRCLE}\ufe0f\u30fb{room_number}")
        await interaction.response.send_message("Room started announced.", ephemeral=True)

    @discord.ui.button(label="Room Closed", style=discord.ButtonStyle.red, row=2)
    async def room_closed(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Announce that the room has closed."""

        if not room_number:
            await interaction.response.send_message("Room number not set.", ephemeral=True)
            return
        await interaction.channel.send(f"\N{LARGE RED CIRCLE}\ufe0f\u30fb{room_number}")
        await interaction.response.send_message("Room closed announced.", ephemeral=True)

    @discord.ui.button(label="Room Shutdown", style=discord.ButtonStyle.red, row=2)
    async def room_shutdown(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Announce that the room is shutting down."""

        await interaction.channel.send("(update-new-room-info)")
        await interaction.response.send_message("Room shutdown announced.", ephemeral=True)

    @discord.ui.button(label="Update New Room Info", style=discord.ButtonStyle.secondary, row=2)
    async def update_room_info_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Prompt for a new room number."""

        await interaction.response.send_modal(UpdateRoomNumberModal())

    @discord.ui.button(
        label="Disable Host Command",
        emoji="🔴",
        style=discord.ButtonStyle.secondary,
        row=3,
    )
    async def disable_host_command(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        channel = interaction.guild.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message(
                f"Channel ID {DISCORD_CHANNEL_ID} not found", ephemeral=True
            )
            return
        await channel.edit(name="〔🔴〕hostbot-disabled")
        roles = []
        if DISCORD_COHOST_ROLE_ID:
            role = interaction.guild.get_role(DISCORD_COHOST_ROLE_ID)
            if role:
                roles.append(role)
        for role in roles:
            await channel.set_permissions(role, view_channel=False)
        embed = discord.Embed(
            description="Host command disabled",
            color=discord.Color.red(),
        )
        embed.set_footer(text=EMBED_FOOTER_TEXT)
        await send_temporary_embed(interaction, embed)

    @discord.ui.button(label="Maintenance", style=discord.ButtonStyle.secondary, row=2)
    async def maintenance(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show embed and queue maintenance tools."""

        await interaction.response.send_message(
            "Maintenance tools:", view=MaintenanceView(), ephemeral=True
        )


# Modal for updating Zoom name
class ZoomNameModal(discord.ui.Modal, title="Update Zoom Name"):
    zoom_name = discord.ui.TextInput(
        label="Enter Zoom Name", placeholder="Your Zoom display name", required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            previous = get_zoom_name_from_file(interaction.user.id)
            prev_name = base64.b64decode(previous).decode() if previous else ""
            encoded_name = save_zoom_name_to_file(interaction.user.id, self.zoom_name.value)
            await interaction.response.send_message(
                f"Zoom name updated and encoded: {encoded_name}", ephemeral=True
            )
            await send_log_embed(
                interaction.client,
                f"Zoom name has been updated for {prev_name} to {self.zoom_name.value}",
                title="NAME CHANGE",
                footer=f"<:discord:1104025337022644254> {interaction.user.display_name}",
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error updating Zoom name: {e}", ephemeral=True
            )


class OpsAssignZoomNameModal(discord.ui.Modal):
    """Modal for admins to assign a Zoom name to another member."""

    def __init__(self, member: discord.Member):
        super().__init__(title="Assign Zoom Name")
        self.member = member
        self.zoom_name = discord.ui.TextInput(
            label="Zoom Name", placeholder="Zoom display name", required=True
        )
        self.add_item(self.zoom_name)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            previous = get_zoom_name_from_file(self.member.id)
            prev_name = base64.b64decode(previous).decode() if previous else ""
            save_zoom_name_to_file(self.member.id, self.zoom_name.value)
            await interaction.response.send_message(
                f"Zoom name for {self.member.mention} updated", ephemeral=True
            )
            await send_log_embed(
                interaction.client,
                f"{interaction.user.display_name} set zoom name for {self.member.display_name} "
                f"from {prev_name} to {self.zoom_name.value}.",
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error updating Zoom name: {e}", ephemeral=True
            )


class AssignCohostModal(discord.ui.Modal, title="Assign Co-Host"):
    """Modal for admins to assign co-host to a user by Zoom name."""

    zoom_name = discord.ui.TextInput(
        label="Zoom Name", placeholder="Zoom display name", required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            encoded_name = base64.b64encode(self.zoom_name.value.encode()).decode()
            await request_queue.put(Request(encoded_name))
            position = request_queue.qsize()
            await interaction.response.send_message(
                f"Co-host assignment for {self.zoom_name.value} has been queued. You are #{position} in line.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(f"Error assigning co-host: {e}", ephemeral=True)


class AssignHostModal(discord.ui.Modal, title="Assign Host"):
    """Modal for admins to assign host by Zoom name."""

    zoom_name = discord.ui.TextInput(
        label="Zoom Name", placeholder="Zoom display name", required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            encoded_name = base64.b64encode(self.zoom_name.value.encode()).decode()
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, send_host_cmd, encoded_name)
            if success:
                await interaction.response.send_message(
                    f"Host assigned to {self.zoom_name.value}", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Failed to send host command", ephemeral=True
                )
        except Exception as e:
            await interaction.response.send_message(f"Error assigning host: {e}", ephemeral=True)


class RevokeCohostModal(discord.ui.Modal, title="Revoke Co-Host"):
    """Modal to revoke co-host privileges by Zoom name.

    This modal is shown when administrators click the **Revoke Co-Host** button
    in the admin panel. Submitting it sends a ``revoke`` TriggerCMD request.
    """

    zoom_name = discord.ui.TextInput(
        label="Zoom Name to Revoke", placeholder="Zoom display name", required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            encoded_name = base64.b64encode(self.zoom_name.value.encode()).decode()
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, send_revoke_cmd, encoded_name)
            if success:
                await interaction.response.send_message(
                    f"Co-host revoked for {self.zoom_name.value}", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Failed to send revoke command", ephemeral=True
                )
        except Exception as e:
            await interaction.response.send_message(f"Error revoking co-host: {e}", ephemeral=True)


class UpdateEmbedTitleModal(discord.ui.Modal, title="Update Embed Title"):
    new_title = discord.ui.TextInput(label="New Title", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        global embed_title
        embed_title = self.new_title.value
        await interaction.response.send_message("Embed title updated.", ephemeral=True)
        await post_host_command(interaction.client)


class UpdateEmbedBodyModal(discord.ui.Modal, title="Update Embed Body"):
    new_body = discord.ui.TextInput(
        label="New Body", style=discord.TextStyle.paragraph, required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        global embed_body
        embed_body = self.new_body.value
        await interaction.response.send_message("Embed body updated.", ephemeral=True)
        await post_host_command(interaction.client)


class UpdateThumbnailModal(discord.ui.Modal, title="Update Thumbnail URL"):
    url = discord.ui.TextInput(label="Thumbnail URL", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        global embed_thumbnail
        embed_thumbnail = self.url.value
        await interaction.response.send_message("Thumbnail updated.", ephemeral=True)
        await post_host_command(interaction.client)


class UpdateFooterModal(discord.ui.Modal, title="Update Footer Text"):
    text = discord.ui.TextInput(label="Footer", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        global embed_footer
        embed_footer = self.text.value
        await interaction.response.send_message("Footer updated.", ephemeral=True)
        await post_host_command(interaction.client)


class UpdateColorModal(discord.ui.Modal, title="Update Embed Color"):
    color = discord.ui.TextInput(label="Color hex (e.g. #FF0000)", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        global embed_color
        try:
            embed_color = discord.Color(int(self.color.value.lstrip("#"), 16))
            await interaction.response.send_message("Color updated.", ephemeral=True)
            await post_host_command(interaction.client)
        except Exception:
            await interaction.response.send_message("Invalid color value.", ephemeral=True)


class SetEmbedRefreshRateModal(discord.ui.Modal, title="Set Embed Refresh Rate"):
    seconds = discord.ui.TextInput(label="Seconds", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        global embed_refresh_interval
        if self.seconds.value.isdigit():
            embed_refresh_interval = int(self.seconds.value)
            await interaction.response.send_message("Refresh rate updated.", ephemeral=True)
        else:
            await interaction.response.send_message("Invalid number.", ephemeral=True)


class SetQueueDelayModal(discord.ui.Modal, title="Set Queue Delay"):
    seconds = discord.ui.TextInput(label="Seconds", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        global queue_delay
        if self.seconds.value.isdigit():
            queue_delay = int(self.seconds.value)
            await interaction.response.send_message("Queue delay updated.", ephemeral=True)
        else:
            await interaction.response.send_message("Invalid number.", ephemeral=True)


class UpdateRoomNumberModal(discord.ui.Modal, title="Update New Room Info"):
    """Modal to set the 11-digit room number."""

    number = discord.ui.TextInput(label="Room Number", required=True, max_length=11)

    async def on_submit(self, interaction: discord.Interaction):
        global room_number
        value = self.number.value.strip()
        if value.isdigit() and len(value) == 11:
            room_number = value
            save_room_number(room_number)
            await interaction.response.send_message(
                f"Room number updated to {room_number}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Invalid room number. Must be 11 digits.",
                ephemeral=True,
            )


class MaintenanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Update Embed Title", style=discord.ButtonStyle.secondary, row=0)
    async def upd_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UpdateEmbedTitleModal())

    @discord.ui.button(label="Update Embed Body", style=discord.ButtonStyle.secondary, row=0)
    async def upd_body(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UpdateEmbedBodyModal())

    @discord.ui.button(label="Thumbnail URL", style=discord.ButtonStyle.secondary, row=1)
    async def upd_thumb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UpdateThumbnailModal())

    @discord.ui.button(label="Update Default Footer", style=discord.ButtonStyle.secondary, row=1)
    async def upd_footer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UpdateFooterModal())

    @discord.ui.button(label="Update Embed Color", style=discord.ButtonStyle.secondary, row=2)
    async def upd_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UpdateColorModal())

    @discord.ui.button(label="Refresh Embed", style=discord.ButtonStyle.success, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await post_host_command(interaction.client)
        await interaction.response.send_message("Embed refreshed.", ephemeral=True)

    @discord.ui.button(label="Set Embed Refresh Rate", style=discord.ButtonStyle.secondary, row=3)
    async def set_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetEmbedRefreshRateModal())

    @discord.ui.button(label="Set Queue Delay", style=discord.ButtonStyle.secondary, row=3)
    async def set_delay(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetQueueDelayModal())

    @discord.ui.button(label="View Firebase Status", style=discord.ButtonStyle.secondary, row=4)
    async def view_fb(self, interaction: discord.Interaction, button: discord.ui.Button):
        from hostbot.storage import _get_realtime_db

        if _get_realtime_db():
            await interaction.response.send_message("Firebase connected", ephemeral=True)
        else:
            await interaction.response.send_message("Firebase not configured", ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.red, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Admin tools:", view=AdminToolsView())


# Helper to (re)post the host command message
async def post_host_command(bot: commands.Bot) -> "discord.Message":
    """Delete the previous host command message, post a new one, and return it."""

    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        logging.error("Channel ID %s not found", DISCORD_CHANNEL_ID)
        return

    message_id = load_host_command_message_id()
    msg = None
    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            msg = None
        except Exception as exc:
            logging.error("Failed to fetch previous host command: %s", exc)
            msg = None
    if msg is None:
        try:
            async for m in channel.history(limit=50):
                if m.author == bot.user and m.embeds:
                    msg = m
                    break
        except Exception as exc:
            logging.error("Failed to search previous host command: %s", exc)
    if msg:
        try:
            await msg.delete()
        except Exception as exc:
            logging.error("Failed to delete previous host command: %s", exc)

    embed = discord.Embed(title=embed_title, description=embed_body, color=embed_color)
    if embed_thumbnail:
        embed.set_thumbnail(url=embed_thumbnail)
    embed.set_footer(text=embed_footer)

    view = HostCommandView()
    message = await channel.send(embed=embed, view=view)
    save_host_command_message_id(message.id)
    return message


# Discord bot
async def start_bot():
    """Initialize and run the Discord bot with command handlers."""
    global request_queue
    request_queue = asyncio.Queue()

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="/", intents=intents)

    async def setup_hook():
        await bot.tree.sync()

    bot.setup_hook = setup_hook

    asyncio.create_task(queue_worker(bot))

    async def refresh_embed_periodically():
        while True:
            await asyncio.sleep(embed_refresh_interval)
            await post_host_command(bot)

    asyncio.create_task(refresh_embed_periodically())

    def start_dashboard():
        def refresh():
            bot.loop.call_soon_threadsafe(asyncio.create_task, post_host_command(bot))

        def get_queue_size() -> int:
            return request_queue.qsize()

        srv = DashboardServer("0.0.0.0", 8000, refresh, get_queue_size)
        srv.start()
        return srv

    global dashboard
    dashboard = start_dashboard()

    @bot.event
    async def on_ready():
        logging.info("Bot logged in as %s", bot.user)
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if channel:
            await send_log_embed(bot, "HostBot is online and ready.")
            await post_host_command(bot)
        else:
            logging.error("Channel ID %s not found", DISCORD_CHANNEL_ID)

    @bot.command(name="embed-host-command")
    async def embed_host_command(ctx):
        """Purge the channel then repost the host command embed."""

        await ctx.channel.purge(limit=None, bulk=False)
        await post_host_command(bot)

    @bot.tree.command(name="embed-host-command", description="Repost the host command embed")
    async def embed_host_command_slash(interaction: discord.Interaction):
        """Slash command wrapper for :func:`post_host_command` that purges the channel."""

        await interaction.channel.purge(limit=None, bulk=False)
        await post_host_command(bot)
        await interaction.response.send_message("Host command reposted.", ephemeral=True)

    @bot.command(name="embed-hostbot")
    async def embed_hostbot(ctx):
        """Purge the channel, repost the host command embed, pin it, and remove the service message."""

        await ctx.channel.purge(limit=None, bulk=False)
        message = await post_host_command(bot)
        if message:
            await message.pin()
            async for pin_msg in ctx.channel.history(limit=1):
                if pin_msg.type == discord.MessageType.pins_add:
                    await pin_msg.delete()

    @bot.tree.command(name="embed-hostbot", description="Repost and pin the host command embed")
    async def embed_hostbot_slash(interaction: discord.Interaction):
        """Slash command variant of embed-hostbot."""

        await interaction.channel.purge(limit=None, bulk=False)
        message = await post_host_command(bot)
        if message:
            await message.pin()
            async for pin_msg in interaction.channel.history(limit=1):
                if pin_msg.type == discord.MessageType.pins_add:
                    await pin_msg.delete()
        await interaction.response.send_message("HostBot embed posted and pinned.", ephemeral=True)

    @bot.tree.command(name="update-room-info", description="Update a channel's room info")
    @app_commands.describe(channel="Channel to update", info="Room information text")
    async def update_room_info(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        info: str,
    ):
        """Set ``channel`` topic to ``info`` and share it in the channel."""

        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return
        await channel.edit(topic=info)
        await channel.send(f"Room info updated:\n{info}")
        await interaction.response.send_message(
            f"Room info updated for {channel.mention}.",
            ephemeral=True,
        )

    @bot.tree.command(name="ops-assign-zoom-name", description="Assign a user's Zoom name")
    async def ops_assign_zoom_name(interaction: discord.Interaction, member: discord.Member):
        """Allow administrators to set a member's Zoom name."""

        allowed_role = None
        if interaction.guild and DISCORD_OPS_ROLE_ID:
            allowed_role = interaction.guild.get_role(DISCORD_OPS_ROLE_ID)

        has_role = allowed_role in interaction.user.roles if allowed_role else False
        is_hardcoded_ops = interaction.user.id in OPS_ADMIN_USER_IDS
        if not (
            interaction.guild
            and (interaction.user.guild_permissions.administrator or has_role or is_hardcoded_ops)
        ):
            await interaction.response.send_message(
                "You do not have permission to use this command.", ephemeral=True
            )
            return

        await interaction.response.send_modal(OpsAssignZoomNameModal(member))

    @bot.event
    async def on_message(message):
        if message.author == bot.user:
            return
        if message.channel.id == DISCORD_CHANNEL_ID:
            try:
                # Assume message content is a base64-encoded name
                encoded_name = message.content.strip()
                base64.b64decode(encoded_name).decode("utf-8")
                await request_queue.put(Request(encoded_name))
                await send_log_embed(
                    bot,
                    f"Queued co-host trigger for encoded name: {encoded_name}",
                )
            except base64.binascii.Error:
                await send_log_embed(bot, "Invalid base64 encoded string")
            except UnicodeDecodeError:
                await send_log_embed(bot, "Decoded string is not valid UTF-8")
        await bot.process_commands(message)

    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.exception("Failed to start bot: %s", e)
    finally:
        await bot.close()
        if dashboard:
            dashboard.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run HostBot")
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Logging level (e.g. INFO, DEBUG)",
    )
    args = parser.parse_args()
    configure_logging(args.log_level)

    DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, DISCORD_BOT_LOG = load_config_from_env()
    if not (DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID and DISCORD_BOT_LOG):
        DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, DISCORD_BOT_LOG = load_config_from_file()
    if DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID and DISCORD_BOT_LOG:
        asyncio.run(start_bot())
    else:
        logging.error(
            "Bot token and channel IDs must be provided via environment variables or the data file."
        )
