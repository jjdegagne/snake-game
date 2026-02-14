import random
import sys
import math
from array import array

import pygame

# Window configuration
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 400
CELL_SIZE = 20
START_LENGTH = 5
LEVELS = {
    1: {"name": "Beginner", "speed": 6},
    2: {"name": "Standard", "speed": 10},
    3: {"name": "Expert", "speed": 14},
}

# Colors (R, G, B)
BG_TOP = (18, 26, 38)
BG_BOTTOM = (9, 14, 22)
GRID_LINE = (30, 44, 61)
HEAD_COLOR = (112, 224, 120)
BODY_COLOR = (66, 168, 90)
FOOD_COLOR = (255, 83, 95)
FOOD_INNER = (255, 178, 184)
WHITE = (240, 240, 240)
SHADOW = (0, 0, 0)
HUD_BASE_SIZE = 22
HUD_MIN_SIZE = 18
SOUND_ENABLED = True
SAMPLE_RATE = 44100

# Grid dimensions derived from window and cell size
GRID_WIDTH = WINDOW_WIDTH // CELL_SIZE
GRID_HEIGHT = WINDOW_HEIGHT // CELL_SIZE


def create_initial_snake(length):
    """Create a horizontal snake that fits the board and can move right safely."""
    if length < 1 or length > GRID_WIDTH:
        raise ValueError("START_LENGTH does not fit within the current grid width.")

    # Center the whole snake horizontally, with segments extending left from the head.
    tail_x = (GRID_WIDTH - length) // 2
    head_x = tail_x + length - 1
    head_y = GRID_HEIGHT // 2

    snake = [(head_x - i, head_y) for i in range(length)]
    return snake


def direction_to_text(direction):
    """Convert a direction vector into a compact label for debug UI."""
    mapping = {
        None: "none",
        (0, -1): "up",
        (0, 1): "down",
        (-1, 0): "left",
        (1, 0): "right",
    }
    return mapping.get(direction, "unknown")


def get_ui_font(size):
    """Load a preferred UI font, then fall back safely to pygame default."""
    preferred = ["Bahnschrift", "Impact", "Segoe UI Black", "Arial Black"]
    for name in preferred:
        path = pygame.font.match_font(name)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


def create_tone(
    frequency_hz,
    duration_ms,
    volume=0.35,
    end_frequency_hz=None,
    attack_ms=8,
    release_ms=60,
):
    """Generate a mono PCM tone/chirp with a soft envelope."""
    sample_count = int(SAMPLE_RATE * (duration_ms / 1000.0))
    if sample_count <= 0:
        sample_count = 1

    amplitude = int(32767 * max(0.0, min(volume, 1.0)))
    attack_samples = int(SAMPLE_RATE * (attack_ms / 1000.0))
    release_samples = int(SAMPLE_RATE * (release_ms / 1000.0))
    release_start = max(0, sample_count - release_samples)
    end_frequency_hz = frequency_hz if end_frequency_hz is None else end_frequency_hz

    pcm = array("h")
    phase = 0.0
    for i in range(sample_count):
        progress = i / max(1, sample_count - 1)
        current_freq = frequency_hz + (end_frequency_hz - frequency_hz) * progress
        phase += (2.0 * math.pi * current_freq) / SAMPLE_RATE

        env = 1.0
        if attack_samples > 0 and i < attack_samples:
            env = i / attack_samples
        if release_samples > 0 and i >= release_start:
            env *= max(0.0, (sample_count - i) / release_samples)

        sample = int(amplitude * env * math.sin(phase))
        pcm.append(sample)

    return pygame.mixer.Sound(buffer=pcm.tobytes())


def init_sounds():
    """Initialize mixer and synth tones; disable gracefully if unavailable."""
    if not SOUND_ENABLED:
        return False, {}

    try:
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1, buffer=512)
        sounds = {
            # Soft pop/chomp: short rounded down-chirp.
            "eat": create_tone(720, 95, 0.26, end_frequency_hz=520, attack_ms=6, release_ms=70),
            # Gentle descending whoosh: longer low sweep.
            "game_over": create_tone(
                420, 420, 0.2, end_frequency_hz=110, attack_ms=16, release_ms=220
            ),
            # Subtle UI click.
            "pause_toggle": create_tone(
                560, 38, 0.16, end_frequency_hz=500, attack_ms=4, release_ms=24
            ),
        }
        return True, sounds
    except pygame.error:
        return False, {}


def play_sound(sound_enabled, sounds, name):
    """Play a named sound if audio is available."""
    if sound_enabled and name in sounds:
        sounds[name].play()


def random_food_position(snake):
    """Return a random grid position that is not occupied by the snake."""
    while True:
        pos = (random.randint(0, GRID_WIDTH - 1), random.randint(0, GRID_HEIGHT - 1))
        if pos not in snake:
            return pos


def draw_background(surface):
    """Draw a gradient background and subtle grid lines."""
    for y in range(WINDOW_HEIGHT):
        t = y / WINDOW_HEIGHT
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        pygame.draw.line(surface, (r, g, b), (0, y), (WINDOW_WIDTH, y))

    for x in range(0, WINDOW_WIDTH, CELL_SIZE):
        pygame.draw.line(surface, GRID_LINE, (x, 0), (x, WINDOW_HEIGHT), 1)
    for y in range(0, WINDOW_HEIGHT, CELL_SIZE):
        pygame.draw.line(surface, GRID_LINE, (0, y), (WINDOW_WIDTH, y), 1)


def grid_rect(grid_pos, padding=0):
    """Return a pixel rectangle for a grid position."""
    x, y = grid_pos
    return pygame.Rect(
        x * CELL_SIZE + padding,
        y * CELL_SIZE + padding,
        CELL_SIZE - padding * 2,
        CELL_SIZE - padding * 2,
    )


def draw_food(surface, grid_pos):
    """Draw a round, highlighted food pellet."""
    rect = grid_rect(grid_pos, padding=2)
    center = rect.center
    radius = rect.width // 2
    pygame.draw.circle(surface, FOOD_COLOR, center, radius)
    pygame.draw.circle(surface, FOOD_INNER, (center[0] - 3, center[1] - 3), max(2, radius // 3))


def draw_food_pop_effects(surface, effects):
    """Draw expanding food-pop rings."""
    for effect in effects:
        progress = 1.0 - (effect["remaining_ms"] / effect["duration_ms"])
        radius = int(6 + 16 * progress)
        alpha = max(0, int(190 * (1.0 - progress)))
        cx = effect["pos"][0] * CELL_SIZE + CELL_SIZE // 2
        cy = effect["pos"][1] * CELL_SIZE + CELL_SIZE // 2
        ring = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(ring, (255, 200, 210, alpha), (radius + 2, radius + 2), radius, 2)
        surface.blit(ring, (cx - radius - 2, cy - radius - 2))


def draw_snake(surface, snake, direction):
    """Draw snake body with rounded corners and a distinct head."""
    for i, segment in enumerate(snake):
        rect = grid_rect(segment, padding=1)
        color = HEAD_COLOR if i == 0 else BODY_COLOR
        pygame.draw.rect(surface, color, rect, border_radius=5)

    # Draw simple eyes so head direction is easy to read.
    head_rect = grid_rect(snake[0], padding=1)
    cx, cy = head_rect.center
    eye_offset = 4
    dx, dy = direction
    if dx == 1:
        eyes = [(cx + eye_offset, cy - 3), (cx + eye_offset, cy + 3)]
    elif dx == -1:
        eyes = [(cx - eye_offset, cy - 3), (cx - eye_offset, cy + 3)]
    elif dy == -1:
        eyes = [(cx - 3, cy - eye_offset), (cx + 3, cy - eye_offset)]
    else:
        eyes = [(cx - 3, cy + eye_offset), (cx + 3, cy + eye_offset)]
    for ex, ey in eyes:
        pygame.draw.circle(surface, SHADOW, (ex, ey), 2)


def draw_hud(surface, score, length, level, level_name, best_score, best_size, size_anim_remaining_ms):
    """Draw top HUD in fixed left/center/right slots with overlap protection."""
    bar = pygame.Rect(12, 12, WINDOW_WIDTH - 24, 58)
    pad = 12
    gap = 10

    panel_surface = pygame.Surface((bar.width, bar.height), pygame.SRCALPHA)
    panel_surface.fill((0, 0, 0, 120))
    surface.blit(panel_surface, bar.topleft)

    left_label = f"Score: {score}"
    mid_label = "Size:"
    size_value_label = f"{length}"
    right_label = f"Level: {level} ({level_name})"
    best_label = f"Best: {best_score}  |  Best Size: {best_size}"

    chosen_font = get_ui_font(HUD_BASE_SIZE)
    left_text = mid_label_text = right_text = size_value_text = None
    for size in range(HUD_BASE_SIZE, HUD_MIN_SIZE - 1, -1):
        test_font = get_ui_font(size)
        l = test_font.render(left_label, True, WHITE)
        m = test_font.render(mid_label, True, WHITE)
        sv = test_font.render(size_value_label, True, WHITE)
        r = test_font.render(right_label, True, WHITE)

        left_x = bar.left + pad
        right_x = bar.right - pad - r.get_width()
        mid_total_w = m.get_width() + 8 + sv.get_width()
        mid_x = WINDOW_WIDTH // 2 - mid_total_w // 2
        left_end = left_x + l.get_width()
        mid_end = mid_x + mid_total_w

        if mid_x >= left_end + gap and mid_end <= right_x - gap:
            chosen_font = test_font
            left_text, mid_label_text, size_value_text, right_text = l, m, sv, r
            break

        chosen_font = test_font
        left_text, mid_label_text, size_value_text, right_text = l, m, sv, r

    small_font = get_ui_font(max(HUD_MIN_SIZE - 2, 14))
    best_text = small_font.render(best_label, True, WHITE)

    top_row_center_y = bar.top + 18
    bottom_row_y = bar.bottom - best_text.get_height() - 6

    left_x = bar.left + pad
    mid_total_w = mid_label_text.get_width() + 8 + size_value_text.get_width()
    mid_x = WINDOW_WIDTH // 2 - mid_total_w // 2
    right_x = bar.right - pad - right_text.get_width()

    surface.blit(left_text, (left_x, top_row_center_y - left_text.get_height() // 2))
    surface.blit(mid_label_text, (mid_x, top_row_center_y - mid_label_text.get_height() // 2))

    # Size-only growth pulse.
    pulse = min(1.0, max(0.0, size_anim_remaining_ms / 400.0))
    scale = 1.0 + 0.2 * pulse
    size_render = size_value_text
    if scale > 1.001:
        glow = pygame.Surface((size_value_text.get_width() + 18, size_value_text.get_height() + 12), pygame.SRCALPHA)
        glow_alpha = int(80 * pulse)
        pygame.draw.ellipse(glow, (255, 210, 80, glow_alpha), glow.get_rect())
        glow_x = mid_x + mid_label_text.get_width() + 4 + (size_value_text.get_width() // 2) - glow.get_width() // 2
        glow_y = top_row_center_y - glow.get_height() // 2
        surface.blit(glow, (glow_x, glow_y))
        size_render = pygame.transform.smoothscale(
            size_value_text,
            (
                max(1, int(size_value_text.get_width() * scale)),
                max(1, int(size_value_text.get_height() * scale)),
            ),
        )

    size_x = mid_x + mid_label_text.get_width() + 8
    size_y = top_row_center_y - size_render.get_height() // 2
    surface.blit(size_render, (size_x, size_y))
    surface.blit(right_text, (right_x, top_row_center_y - right_text.get_height() // 2))
    surface.blit(best_text, (bar.centerx - best_text.get_width() // 2, bottom_row_y))


def wrap_text_to_width(text, font, max_width, max_lines=2):
    """Wrap a string into at most max_lines for the provided width."""
    words = text.split(" ")
    if not words:
        return [""]

    lines = []
    current = words[0]

    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.size(candidate)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break

    lines.append(current)
    remaining_words = words[len(" ".join(lines).split(" ")):]
    if remaining_words and len(lines) == max_lines:
        ellipsis = "..."
        while font.size(lines[-1] + ellipsis)[0] > max_width and lines[-1]:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip() + ellipsis

    return lines[:max_lines]


def draw_bottom_bar(surface, font):
    """Draw a compact bottom control bar."""
    text = "H: help  |  P: pause  |  R: restart  |  Esc: quit"
    label = font.render(text, True, WHITE)
    panel_h = font.get_height() + 10
    panel_rect = pygame.Rect(12, WINDOW_HEIGHT - panel_h - 8, WINDOW_WIDTH - 24, panel_h)
    panel_surface = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
    panel_surface.fill((0, 0, 0, 120))
    surface.blit(panel_surface, panel_rect.topleft)
    surface.blit(label, label.get_rect(center=panel_rect.center))


def draw_debug_status(surface, font, paused, direction, game_over_reason):
    """Draw debug line when debug mode is enabled."""
    debug = (
        f"paused={str(paused).lower()}  "
        f"direction={direction_to_text(direction)}  "
        f"game_over_reason={game_over_reason}"
    )
    text = font.render(debug, True, WHITE)
    panel_h = font.get_height() + 8
    panel_rect = pygame.Rect(12, WINDOW_HEIGHT - panel_h - 46, WINDOW_WIDTH - 24, panel_h)
    panel_surface = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
    panel_surface.fill((0, 0, 0, 120))
    surface.blit(panel_surface, panel_rect.topleft)
    surface.blit(text, (panel_rect.left + 8, panel_rect.top + 4))


def draw_help_overlay(surface, title_font, text_font):
    """Draw centered help panel with full controls."""
    lines = [
        "Arrows: move",
        "1/2/3: change level",
        "P: pause",
        "R: restart",
        "Esc: quit",
        "Size increases when you eat food.",
    ]
    title = title_font.render("Controls", True, WHITE)
    line_surfaces = [text_font.render(line, True, WHITE) for line in lines]
    content_w = max(title.get_width(), max(s.get_width() for s in line_surfaces))
    content_h = title.get_height() + 14 + len(line_surfaces) * (text_font.get_height() + 6) - 6

    panel_rect = pygame.Rect(0, 0, content_w + 48, content_h + 36)
    panel_rect.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
    panel_surface = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
    panel_surface.fill((0, 0, 0, 190))
    surface.blit(panel_surface, panel_rect.topleft)

    y = panel_rect.top + 18
    surface.blit(title, title.get_rect(centerx=panel_rect.centerx, y=y))
    y += title.get_height() + 14
    for line_surface in line_surfaces:
        surface.blit(line_surface, line_surface.get_rect(centerx=panel_rect.centerx, y=y))
        y += text_font.get_height() + 6


def draw_level_toast(surface, font, level, level_name):
    """Draw a short centered toast when level changes."""
    text_surface = font.render(f"Level {level}: {level_name}", True, WHITE)
    box = text_surface.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 70))
    box.inflate_ip(28, 14)
    panel = pygame.Surface((box.width, box.height), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 180))
    surface.blit(panel, box.topleft)
    surface.blit(text_surface, text_surface.get_rect(center=box.center))


def draw_paused_overlay(surface, font):
    """Draw a compact paused label centered on screen."""
    label = font.render("Paused", True, WHITE)
    box = label.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
    box.inflate_ip(26, 16)
    panel = pygame.Surface((box.width, box.height), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 160))
    surface.blit(panel, box.topleft)
    surface.blit(label, label.get_rect(center=box.center))


def show_game_over(screen, font, controls_font, score):
    """Display game-over screen and wait for restart/quit controls."""
    clock = pygame.time.Clock()

    draw_background(screen)
    msg1 = font.render("Game Over", True, WHITE)
    msg2 = font.render(f"Score: {score}", True, WHITE)
    msg3 = controls_font.render("Press R to restart or Esc to quit", True, WHITE)

    screen.blit(msg1, (WINDOW_WIDTH // 2 - msg1.get_width() // 2, WINDOW_HEIGHT // 2 - 50))
    screen.blit(msg2, (WINDOW_WIDTH // 2 - msg2.get_width() // 2, WINDOW_HEIGHT // 2 - 10))
    screen.blit(msg3, (WINDOW_WIDTH // 2 - msg3.get_width() // 2, WINDOW_HEIGHT // 2 + 30))
    pygame.display.flip()

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    return "restart"
                if event.key == pygame.K_ESCAPE:
                    return "quit"
        clock.tick(15)


def main():
    pygame.mixer.pre_init(SAMPLE_RATE, -16, 1, 512)
    pygame.init()
    pygame.display.set_caption("Simple Snake")
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    clock = pygame.time.Clock()
    font = get_ui_font(22)
    controls_font = get_ui_font(15)
    help_title_font = get_ui_font(26)
    toast_font = get_ui_font(20)
    sound_enabled, sounds = init_sounds()
    best_score = 0
    best_size = START_LENGTH

    while True:
        # Start snake with a guaranteed valid in-bounds shape.
        snake = create_initial_snake(START_LENGTH)

        food = random_food_position(snake)
        score = 0
        paused = False
        restart_requested = False
        game_over_reason = "none"
        level = 2
        direction = None
        next_direction = None
        show_help = False
        show_debug = False
        level_toast_remaining_ms = 0
        size_anim_remaining_ms = 0
        food_pop_effects = []
        last_tick_ms = pygame.time.get_ticks()

        running = True
        while running:
            now_ms = pygame.time.get_ticks()
            dt_ms = max(0, now_ms - last_tick_ms)
            last_tick_ms = now_ms

            level_name = LEVELS[level]["name"]
            current_speed = LEVELS[level]["speed"]
            # Handle window and keyboard events.
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit()
                    if event.key == pygame.K_r:
                        restart_requested = True
                    elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                        key_to_level = {pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3}
                        level = key_to_level[event.key]
                        level_name = LEVELS[level]["name"]
                        current_speed = LEVELS[level]["speed"]
                        level_toast_remaining_ms = 1000
                    elif event.key == pygame.K_h:
                        show_help = not show_help
                    elif event.key == pygame.K_d:
                        show_debug = not show_debug
                    elif event.key == pygame.K_p:
                        paused = not paused
                        play_sound(sound_enabled, sounds, "pause_toggle")
                    elif event.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT):
                        key_to_dir = {
                            pygame.K_UP: (0, -1),
                            pygame.K_DOWN: (0, 1),
                            pygame.K_LEFT: (-1, 0),
                            pygame.K_RIGHT: (1, 0),
                        }
                        candidate = key_to_dir[event.key]

                        if direction is None:
                            # On first move, reject directions that collide with body or wall.
                            hx, hy = snake[0]
                            nx, ny = hx + candidate[0], hy + candidate[1]
                            in_bounds = 0 <= nx < GRID_WIDTH and 0 <= ny < GRID_HEIGHT
                            if in_bounds and (nx, ny) not in snake[1:]:
                                next_direction = candidate
                        else:
                            opposite = (-direction[0], -direction[1])
                            if candidate != opposite:
                                next_direction = candidate

            if restart_requested:
                break

            if paused:
                draw_background(screen)
                draw_food(screen, food)
                draw_food_pop_effects(screen, food_pop_effects)
                draw_snake(screen, snake, direction or (1, 0))
                draw_hud(
                    screen,
                    score,
                    len(snake),
                    level,
                    level_name,
                    best_score,
                    best_size,
                    size_anim_remaining_ms,
                )
                draw_bottom_bar(screen, controls_font)
                if show_debug:
                    draw_debug_status(screen, controls_font, paused, direction, game_over_reason)
                if show_help:
                    draw_help_overlay(screen, help_title_font, controls_font)
                if level_toast_remaining_ms > 0:
                    draw_level_toast(screen, toast_font, level, level_name)
                hint = controls_font.render("1-3: change level", True, WHITE)
                screen.blit(hint, (24, 56))
                draw_paused_overlay(screen, font)
                pygame.display.flip()
                clock.tick(15)
                continue

            if next_direction is not None:
                direction = next_direction

            # Do not move until the player chooses an initial direction.
            if direction is None:
                draw_background(screen)
                draw_food(screen, food)
                draw_food_pop_effects(screen, food_pop_effects)
                draw_snake(screen, snake, (1, 0))
                draw_hud(
                    screen,
                    score,
                    len(snake),
                    level,
                    level_name,
                    best_score,
                    best_size,
                    size_anim_remaining_ms,
                )
                draw_bottom_bar(screen, controls_font)
                if show_debug:
                    draw_debug_status(screen, controls_font, paused, direction, game_over_reason)
                if show_help:
                    draw_help_overlay(screen, help_title_font, controls_font)
                if level_toast_remaining_ms > 0:
                    draw_level_toast(screen, toast_font, level, level_name)
                hint = controls_font.render("1-3: change level", True, WHITE)
                screen.blit(hint, (24, 56))
                pygame.display.flip()
                clock.tick(15)
                continue

            if level_toast_remaining_ms > 0:
                level_toast_remaining_ms = max(0, level_toast_remaining_ms - dt_ms)
            if size_anim_remaining_ms > 0:
                size_anim_remaining_ms = max(0, size_anim_remaining_ms - dt_ms)
            for effect in food_pop_effects:
                effect["remaining_ms"] = max(0, effect["remaining_ms"] - dt_ms)
            food_pop_effects = [e for e in food_pop_effects if e["remaining_ms"] > 0]

            # Compute new head position from current direction.
            head_x, head_y = snake[0]
            dx, dy = direction
            new_head = (head_x + dx, head_y + dy)
            will_grow = new_head == food

            # Game over if snake hits wall.
            hit_wall = (
                new_head[0] < 0
                or new_head[0] >= GRID_WIDTH
                or new_head[1] < 0
                or new_head[1] >= GRID_HEIGHT
            )

            # Game over if snake runs into itself.
            # Moving into the current tail cell is valid when not growing,
            # because that tail segment moves away on this tick.
            body_to_check = snake if will_grow else snake[:-1]
            hit_self = new_head in body_to_check

            if hit_wall or hit_self:
                game_over_reason = "wall" if hit_wall else "self"
                play_sound(sound_enabled, sounds, "game_over")
                running = False
                break

            # Move snake by inserting new head.
            snake.insert(0, new_head)

            # Grow snake if food is eaten, otherwise remove tail to keep length.
            if will_grow:
                eaten_food_pos = food
                score += 1
                food = random_food_position(snake)
                play_sound(sound_enabled, sounds, "eat")
                size_anim_remaining_ms = 400
                food_pop_effects.append(
                    {"pos": eaten_food_pos, "duration_ms": 250, "remaining_ms": 250}
                )
                best_score = max(best_score, score)
                best_size = max(best_size, len(snake))
            else:
                snake.pop()

            # Draw everything.
            draw_background(screen)
            draw_food(screen, food)
            draw_food_pop_effects(screen, food_pop_effects)
            draw_snake(screen, snake, direction)
            draw_hud(
                screen,
                score,
                len(snake),
                level,
                level_name,
                best_score,
                best_size,
                size_anim_remaining_ms,
            )
            draw_bottom_bar(screen, controls_font)
            if show_debug:
                draw_debug_status(screen, controls_font, paused, direction, game_over_reason)
            if show_help:
                draw_help_overlay(screen, help_title_font, controls_font)
            if level_toast_remaining_ms > 0:
                draw_level_toast(screen, toast_font, level, level_name)
            hint = controls_font.render("1-3: change level", True, WHITE)
            screen.blit(hint, (24, 56))

            pygame.display.flip()
            clock.tick(current_speed)

        if restart_requested:
            continue

        action = show_game_over(screen, font, controls_font, score)
        if action == "restart":
            continue
        break

    pygame.quit()


if __name__ == "__main__":
    main()
