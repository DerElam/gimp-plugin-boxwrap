"""This is a plugin for GIMP that assists in creating a printable
wrap for board game boxes.
"""

from gimpfu import gimp, pdb
import gimpfu


# We are assuming a 300 dpi images
DPI = 300.0  # type: float


class PausedUndo:
    """Context guard that temporarily disables the undo history."""

    def __init__(self, image):
        # type: (gimp.Image) -> None
        self.image = image

    def __enter__(self):
        # type: () -> None
        self.image.disable_undo()

    def __exit__(self, exception_type, value, traceback):
        self.image.enable_undo()
        return False


class DefaultContext:
    """Context guard that restores the current gimp context at the end."""

    def __enter__(self):
        # type: () -> None
        gimp.context_push()
        pdb.gimp_context_set_defaults()

    def __exit__(self, exception_type, value, traceback):
        gimp.context_pop()
        return False


class Corner:
    """Enumerates four corners and the center of a rectangle."""

    TOP_LEFT = 1                # type: int
    TOP_RIGHT = 2               # type: int
    BOTTOM_LEFT = 3             # type: int
    BOTTOM_RIGHT = 4            # type: int
    CENTER = 5                  # type: int


class Direction:
    """Enumerates the four principal directions on a page."""

    LEFT = 1                    # type: int
    RIGHT = 2                   # type: int
    UP = 3                      # type: int
    DOWN = 4                    # type: int


def mm_to_px(mm):
    # type: (float) -> int
    """Converts pixels to millimeters."""

    return int(round(mm / 25.4 * DPI))


def px_to_mm(px):
    # type: (float) -> float
    """Converts millimeters to pixels."""

    return (px * 25.4) / DPI


def move_drawable_to(drawable,  # type: gimp.Image
                     corner,    # type: Corner
                     x,         # type: int
                     y          # type: int
                     ):
    # type: (...) -> None
    """Moves a corner of a drawable to the position (x, y)."""

    left, top = pdb.gimp_drawable_offsets(drawable)              # type: int, int
    width, height = pdb.gimp_drawable_mask_bounds(drawable)[3:]  # type: int, int
    right = left + width                                         # type: int
    bottom = top + height                                        # type: int
    dx, dy = 0, 0                                                # type: int
    if corner == Corner.TOP_LEFT:
        dx = x - left
        dy = y - top
    elif corner == Corner.TOP_RIGHT:
        dx = x - right
        dy = y - top
    elif corner == Corner.BOTTOM_LEFT:
        dx = x - left
        dy = y - bottom
    elif corner == Corner.BOTTOM_RIGHT:
        dx = x - right
        dy = y - bottom
    elif corner == Corner.CENTER:
        dx = x - (left + right) // 2
        dy = y - (top + bottom) // 2
    else:
        gimp.message("Invalid corner %s" % repr(corner))
        return
    pdb.gimp_layer_translate(drawable, dx, dy)


def copy_and_rotate_rectangle(src_image,   # type: gimp.Image
                              src_x,       # type: int
                              src_y,       # type: int
                              src_width,   # type: int
                              src_height,  # type: int
                              dst_layer,   # type: gimp.Layer
                              dst_x,       # type: int
                              dst_y,       # type: int
                              dst_corner,  # type: Corner
                              angle        # type: int
                              ):
    # type: (...) -> None
    """Copies a rectangular region from one image to another while also
    rotating it.
    """

    pdb.gimp_image_select_rectangle(src_image, gimpfu.CHANNEL_OP_REPLACE,
                                    src_x, src_y, src_width, src_height)
    pdb.gimp_edit_copy_visible(src_image)
    pdb.gimp_selection_none(src_image)

    # Paste into dst as a floating selection
    floating = pdb.gimp_edit_paste(dst_layer, gimpfu.TRUE)  # type: gimp.Layer

    # Rotate floating selection if needed
    angles = {90: gimpfu.ROTATE_90,
              180: gimpfu.ROTATE_180,
              270: gimpfu.ROTATE_270}  # type: int
    if angle in angles:
        rotation = angles[angle]  # type: int
        pdb.gimp_drawable_transform_rotate_simple(floating, rotation,
                                                  gimpfu.FALSE, 0, 0,
                                                  gimpfu.FALSE)

    # Move floating selection into position and anchor it
    move_drawable_to(floating, dst_corner, dst_x, dst_y)
    pdb.gimp_floating_sel_anchor(floating)


def draw_mark(image,            # type: gimp.Image
              directions,
              x0,               # type: int
              y0,               # type: int
              size,             # type: int
              distance          # type: int
              ):
    # type: (...) -> None
    """Draws a mark at position where one must cut or fold the paper."""

    x, y, width, height = 0, 0, 0, 0  # type: int, int, int, int

    for direction in directions:  # type: Direction
        if direction == Direction.UP:
            x = x0 - 1
            y = y0 - distance - size
            width = 2
            height = size
        elif direction == Direction.DOWN:
            x = x0 - 1
            y = y0 + distance
            width = 2
            height = size
        elif direction == Direction.LEFT:
            x = x0 - distance - size
            y = y0 - 1
            width = size
            height = 2
        elif direction == Direction.RIGHT:
            x = x0 + distance
            y = y0 - 1
            width = size
            height = 2
        else:
            gimp.message("Invalid direction %s" % repr(direction))
            return

        pdb.gimp_image_select_rectangle(image, gimpfu.CHANNEL_OP_REPLACE,
                                        x, y, width, height)
        pdb.gimp_edit_fill(image.active_layer, gimpfu.FILL_FOREGROUND)
        pdb.gimp_selection_none(image)


def template_coordinates(box_width,   # type: int
                         box_height,  # type: int
                         box_depth    # type: int
                         ):
    """Calculates a few important coordinates in the template image given
    the box size."""

    # The template layout looks like this:
    #
    #    x0         x1         x2        x3         x4
    #
    # y0 o          +----------+                       -
    #               |          |                       ^
    #               |   TOP    |                       | depth
    #               |          |                       v
    # y1 +----------+----------+---------+----------+  -
    #    |          |          |         |          |  ^
    # y2 |---LEFT---|--FRONT---|--RIGHT--|---BACK---|  | height
    #    |          |          |         |          |  v
    # y3 +----------+----------+---------+----------+  -
    #               |          |                       ^
    #               |  BOTTOM  |                       | depth
    #               |          |                       v
    # y4            +----------+                       -
    #
    #     |<------->|<-------->|<------->|<-------->|
    #        depth     width      depth     width

    x0 = 0                      # type: int
    x1 = x0 + box_depth         # type: int
    x2 = x1 + box_width         # type: int
    x3 = x2 + box_depth         # type: int
    x4 = x3 + box_width         # type: int

    y0 = 0                      # type: int
    y1 = y0 + box_depth         # type: int
    y2 = y1 + box_height // 2   # type: int
    y3 = y1 + box_height        # type: int
    y4 = y3 + box_depth         # type: int

    return ((x0, x1, x2, x3, x4), (y0, y1, y2, y3, y4))


def wrap_coordinates(box_width,            # type: int
                     box_height,           # type: int
                     box_depth,            # type: int
                     thickness,            # type: int
                     inside_size,          # type: int
                     flap_size,            # type: int
                     crop_mark_size,       # type: int
                     crop_mark_distance    # type: int
                     ):
    """Calculates a few important coordinates in the wrap image
    given the box size and a few other dimensions."""

    # The wrap layout looks like this:
    #     0   x1      x2 x3       x4  x5           x6  x7      x8 x9      x10 x11
    #
    # 0   o                       |   |            |   |
    #
    # y1                      --  +---+------------+---+  --
    #                             |   |            |   |
    #                             |   |  inside    |   |
    #                             |   |            |   |
    # y2                          +...+............+...+
    #                             |   |            |   |
    # y3                          +...+............+...+
    #                             | f |            | f |
    #                             | l |   front    | l |
    #         |                   | a |   /back    | a |                   |
    #                             | p |            | p |
    # y4  --  +--------+-+--------+---+------------+---+--------+-+--------+  --
    # y5      |........|.|............|            |............|.|........|
    #         | inside | | left/right | top/bottom | left/right | | inside |
    # y6      |........|.|............|            |............|.|........|
    # y7  --  +--------+-+--------+---+------------+---+--------+-+--------+  --
    #                             | f |            | f |
    #         |                   | l |   front    | l |                   |
    #                             | a |   /back    | a |
    #                             | p |            | p |
    # y8                          +...+............+...+
    #                             |   |            |   |
    # y9                          +...+............+...+
    #                             |   |            |   |
    #                             |   |  inside    |   |
    #                             |   |            |   |
    # y10                     --  +---+------------+---+  --
    #
    # y11                         |   |            |   |

    half_box_height = box_height // 2                # type: int

    x1 = crop_mark_size + crop_mark_distance         # type: int
    x2 = x1 + inside_size                            # type: int
    x3 = x2 + thickness                              # type: int
    x5 = x3 + half_box_height                        # type: int
    x4 = x5 - flap_size                              # type: int
    x6 = x5 + box_width                              # type: int
    x7 = x6 + flap_size                              # type: int
    x8 = x6 + half_box_height                        # type: int
    x9 = x8 + thickness                              # type: int
    x10 = x9 + inside_size                           # type: int
    x11 = x10 + crop_mark_distance + crop_mark_size  # type: int

    y1 = crop_mark_size + crop_mark_distance         # type: int
    y2 = y1 + inside_size                            # type: int
    y3 = y2 + thickness                              # type: int
    y4 = y3 + half_box_height                        # type: int
    y5 = y4 + flap_size                              # type: int
    y7 = y4 + box_depth                              # type: int
    y6 = y7 - flap_size                              # type: int
    y8 = y7 + half_box_height                        # type: int
    y9 = y8 + thickness                              # type: int
    y10 = y9 + inside_size                           # type: int
    y11 = y10 + crop_mark_distance + crop_mark_size  # type: int

    return ((0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11),
            (0, y1, y2, y3, y4, y5, y6, y7, y8, y9, y10, y11))


def create_template(box_width_mm,   # type: float
                    box_height_mm,  # type: float
                    box_depth_mm    # type: float
                    ):
    # type: (...) -> None
    """Creates an empty template image given the box size."""

    with DefaultContext():
        box_width = mm_to_px(box_width_mm)    # type: int
        box_height = mm_to_px(box_height_mm)  # type: int
        box_depth = mm_to_px(box_depth_mm)    # type: int

        xs, ys = template_coordinates(box_width, box_height, box_depth)
        image_width = xs[-1] - xs[0]   # type: int
        image_height = ys[-1] - ys[0]  # type: int

        # Create a template image with one transparent layer
        image = gimp.Image(image_width, image_height)  # type: gimp.Image

        with PausedUndo(image):
            layer = gimp.Layer(image,
                               "Template",
                               image_width,
                               image_height,
                               gimpfu.RGBA_IMAGE,
                               100,
                               gimpfu.NORMAL_MODE)  # type: gimp.Layer
            image.add_layer(layer, 0)

            # Create guides
            for x in xs:        # type: int
                image.add_vguide(x)
            for y in ys:        # type: int
                image.add_hguide(y)

            # Fill the areas where the graphics go with white
            pdb.gimp_selection_none(image)
            pdb.gimp_progress_pulse()
            pdb.gimp_image_select_rectangle(image, gimpfu.CHANNEL_OP_ADD,
                                            xs[0], ys[1],
                                            image_width, ys[3]-ys[1])
            pdb.gimp_progress_pulse()
            pdb.gimp_image_select_rectangle(image, gimpfu.CHANNEL_OP_ADD,
                                            xs[1], ys[0],
                                            xs[2]-xs[1], image_height)
            pdb.gimp_edit_fill(layer, gimpfu.FILL_WHITE)
            pdb.gimp_selection_none(image)

            def put_text(text, left, right, top, bottom):
                """Puts some text in the center of a rectangle."""

                pdb.gimp_progress_pulse()
                text_size = DPI / 4  # type: int
                text_layer = pdb.gimp_text_layer_new(
                    image, text, "sans-serif", text_size,
                    gimpfu.PIXELS)  # type: gimp.Layer
                image.add_layer(text_layer, 0)
                move_drawable_to(text_layer, Corner.CENTER,
                                 (left + right) // 2,
                                 (top + bottom) // 2)
                pdb.gimp_image_merge_down(image, text_layer,
                                          gimpfu.CLIP_TO_BOTTOM_LAYER)

            put_text("TOP", xs[1], xs[2], ys[0], ys[1])
            put_text("LEFT", xs[0], xs[1], ys[1], ys[3])
            put_text("FRONT", xs[1], xs[2], ys[1], ys[3])
            put_text("RIGHT", xs[2], xs[3], ys[1], ys[3])
            put_text("BACK", xs[3], xs[4], ys[1], ys[3])
            put_text("BOTTOM", xs[1], xs[2], ys[3], ys[4])
            put_text("Box width: %dmm (%dpx)\n"
                     "Box height: %dmm (%dpx)\n"
                     "Box depth: %dmm (%dpx)" %
                     (box_width_mm, box_width,
                      box_height_mm, box_height,
                      box_depth_mm, box_depth),
                     xs[0], xs[1], ys[0], ys[1])

            gimp.Display(image)
    gimp.displays_flush()


def create_wraps(src_image,             # type: gimp.Image
                 box_width_mm,          # type: float
                 box_height_mm,         # type: float
                 box_depth_mm,          # type: float
                 thickness_mm,          # type: float
                 flap_size_mm,          # type: float
                 inside_size_mm,        # type: float
                 crop_mark_size_mm,     # type: float
                 crop_mark_distance_mm  # type: float
                 ):
    # type: (...) -> None
    """Creates two wrap images from a template image."""

    # Convert the dimensions from mm to px
    box_width = mm_to_px(box_width_mm)                    # type: int
    box_height = mm_to_px(box_height_mm)                  # type: int
    box_depth = mm_to_px(box_depth_mm)                    # type: int
    thickness = mm_to_px(thickness_mm)                    # type: int
    flap_size = mm_to_px(flap_size_mm)                    # type: int
    inside_size = mm_to_px(inside_size_mm)                # type: int
    crop_mark_size = mm_to_px(crop_mark_size_mm)          # type: int
    crop_mark_distance = mm_to_px(crop_mark_distance_mm)  # type: int

    half_box_height = box_height // 2  # type: int
    half_box_height_plus_extra = \
        half_box_height + thickness + inside_size  # type: int

    # Coordinates in the source image
    src_xs, src_ys = template_coordinates(
        box_width, box_height, box_depth)  # type: int, int
    src_image_width = src_xs[-1] - src_xs[0]   # type: int
    src_image_height = src_ys[-1] - src_ys[0]  # type: int

    # Coordinates in the destination images
    dst_xs, dst_ys = wrap_coordinates(
        box_width, box_height, box_depth,
        thickness, inside_size, flap_size,
        crop_mark_size, crop_mark_distance)
    dst_image_width = dst_xs[-1] - dst_xs[0]   # type: int
    dst_image_height = dst_ys[-1] - dst_ys[0]  # type: int

    # Make sure we have the right dimensions
    if src_image.width != src_image_width or \
       src_image.height != src_image_height:
        gimp.message("Template image has the wrong size. "
                     "Expected %dpx x %dpx (%dmm x %dmm) "
                     "but got %dpx x %dpx (%dmm x %dmm)."
                     % (src_image_width,
                        src_image_height,
                        px_to_mm(src_image_width),
                        px_to_mm(src_image_height),
                        src_image.width,
                        src_image.height,
                        px_to_mm(src_image.width),
                        px_to_mm(src_image.height)))
        return

    # Draw stuff onto both destination images in the same way
    def draw(dst_image, copy_and_rotate_definitions):
        """Copies regions from the input image to a wrap image."""

        dst_layer = gimp.Layer(dst_image, "Wrap", dst_image_width,
                               dst_image_height, gimpfu.RGB_IMAGE,
                               100, gimpfu.NORMAL_MODE)  # type: gimp.Layer
        dst_layer.fill(gimpfu.FILL_WHITE)
        dst_image.add_layer(dst_layer, 0)

        # Add guides
        for x in dst_xs:        # type: int
            dst_image.add_vguide(x)
        for y in dst_ys:        # type: int
            dst_image.add_hguide(y)

        # Take the layers from the template and move and rotate them
        # into position
        for d in copy_and_rotate_definitions:
            pdb.gimp_progress_pulse()
            copy_and_rotate_rectangle(
                src_image,      # src_image
                d[0],           # src_x
                d[1],           # src_y
                d[2],           # src_width
                d[3],           # src_height
                dst_layer,      # dst_layer
                d[4],           # dst_x
                d[5],           # dst_y
                d[6],           # dst_corner
                d[7])           # rotation_angle

        # Copy strips from the sides to create the flaps on the front
        # and the back
        pdb.gimp_progress_pulse()
        copy_and_rotate_rectangle(
            dst_image, dst_xs[1], dst_ys[4],
            half_box_height_plus_extra, flap_size,
            dst_layer, dst_xs[5], dst_ys[4],
            Corner.BOTTOM_RIGHT, 90)

        pdb.gimp_progress_pulse()
        copy_and_rotate_rectangle(
            dst_image, dst_xs[1], dst_ys[6],
            half_box_height_plus_extra, flap_size,
            dst_layer, dst_xs[5], dst_ys[7],
            Corner.TOP_RIGHT, 270)

        pdb.gimp_progress_pulse()
        copy_and_rotate_rectangle(
            dst_image, dst_xs[6], dst_ys[4],
            half_box_height_plus_extra, flap_size,
            dst_layer, dst_xs[6], dst_ys[4],
            Corner.BOTTOM_LEFT, 270)

        pdb.gimp_progress_pulse()
        copy_and_rotate_rectangle(
            dst_image, dst_xs[6], dst_ys[6],
            half_box_height_plus_extra, flap_size,
            dst_layer, dst_xs[6], dst_ys[7],
            Corner.TOP_LEFT, 90)

        # Marks for cutting and folding
        draw_mark(dst_image, (Direction.UP, Direction.LEFT),
                  dst_xs[4], dst_ys[1], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP,),
                  dst_xs[5], dst_ys[1], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP,),
                  dst_xs[6], dst_ys[1], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP, Direction.RIGHT),
                  dst_xs[7], dst_ys[1], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP, Direction.LEFT),
                  dst_xs[1], dst_ys[4], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.UP, Direction.RIGHT),
                  dst_xs[10], dst_ys[4], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN, Direction.LEFT),
                  dst_xs[1], dst_ys[7], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN, Direction.RIGHT),
                  dst_xs[10], dst_ys[7], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN, Direction.LEFT),
                  dst_xs[4], dst_ys[10], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN,),
                  dst_xs[5], dst_ys[10], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN,),
                  dst_xs[6], dst_ys[10], crop_mark_size, crop_mark_distance)
        draw_mark(dst_image, (Direction.DOWN, Direction.RIGHT),
                  dst_xs[7], dst_ys[10], crop_mark_size, crop_mark_distance)

        pdb.gimp_selection_none(dst_image)

    # Define where from and where to we want to copy
    # Each line looks like this:
    # (src_x, src_y, src_width, src_height,
    #  dst_x, dst_y, dst_corner, rotation_angle)
    copy_and_rotate_definitions_top = (
        # Top
        (src_xs[1], src_ys[0], box_width, box_depth,
         dst_xs[5], dst_ys[4], Corner.TOP_LEFT, 0),
        # Left
        (src_xs[0], src_ys[1], box_depth, half_box_height_plus_extra,
         dst_xs[5], dst_ys[4], Corner.TOP_RIGHT, 90),
        # Front
        (src_xs[1], src_ys[1], box_width, half_box_height_plus_extra,
         dst_xs[5], dst_ys[7], Corner.TOP_LEFT, 0),
        # Right
        (src_xs[2], src_ys[1], box_depth, half_box_height_plus_extra,
         dst_xs[6], dst_ys[4], Corner.TOP_LEFT, 270),
        # Back
        (src_xs[3], src_ys[1], box_width, half_box_height_plus_extra,
         dst_xs[5], dst_ys[4], Corner.BOTTOM_LEFT, 180),
    )

    copy_and_rotate_definitions_bottom = (
        # Left
        (src_xs[0], src_ys[3] - half_box_height_plus_extra, box_depth,
         half_box_height_plus_extra, dst_xs[5], dst_ys[4], Corner.TOP_RIGHT, 270),
        # Front
        (src_xs[1], src_ys[3] - half_box_height_plus_extra, box_width,
         half_box_height_plus_extra, dst_xs[5], dst_ys[1], Corner.TOP_LEFT, 0),
        # Right
        (src_xs[2], src_ys[3] - half_box_height_plus_extra, box_depth,
         half_box_height_plus_extra, dst_xs[6], dst_ys[4], Corner.TOP_LEFT, 90),
        # Back
        (src_xs[3], src_ys[3] - half_box_height_plus_extra, box_width,
         half_box_height_plus_extra, dst_xs[5], dst_ys[10], Corner.BOTTOM_LEFT, 180),
        # Bottom
        (src_xs[1], src_ys[3], box_width, box_depth,
         dst_xs[5], dst_ys[4], Corner.TOP_LEFT, 0),
    )

    with DefaultContext():
        dst_image_top = gimp.Image(dst_image_width,
                                   dst_image_height,
                                   gimpfu.RGB)  # type: gimp.Image
        with PausedUndo(dst_image_top):
            draw(dst_image_top, copy_and_rotate_definitions_top)
            gimp.Display(dst_image_top)

        dst_image_bottom = gimp.Image(dst_image_width,
                                      dst_image_height,
                                      gimpfu.RGB)  # type: gimp.Image
        with PausedUndo(dst_image_bottom):
            draw(dst_image_bottom, copy_and_rotate_definitions_bottom)
            gimp.Display(dst_image_bottom)
    gimp.displays_flush()


PLUGIN_AUTHOR = "Elam Kolenovic"
PLUGIN_COPYRIGHT = "Elam Kolenovic"
PLUGIN_DATE = "2019-11-23"
PLUGIN_MENU = "<Toolbox>/Filters/Boardgames/Box Wrap/"

gimpfu.register(
    "Boxwrap_Create_Template",
    """
    Box width: Distance between left and right face
    Box height: Distance between top and bottom face
    Box depth: Distance between front and back face
    """,
    "Create an empty template image for the printable box wrap",
    PLUGIN_AUTHOR,
    PLUGIN_COPYRIGHT,
    PLUGIN_DATE,
    PLUGIN_MENU + "Create empty template...",
    "",
    [
        (gimpfu.PF_ADJUSTMENT, "width",
         "Box width [mm]",
         75, (10, 500, 1)),
        (gimpfu.PF_ADJUSTMENT, "height",
         "Box height [mm]",
         104, (10, 500, 1)),
        (gimpfu.PF_ADJUSTMENT, "depth",
         "Box depth [mm]",
         100, (10, 500, 1))
    ],
    [],
    create_template
)

gimpfu.register(
    "Boxwrap_Create_Wraps",
    """
    The dimensions must be the same as in the template dialog!

    Box width: Distance between left and right face
    Box height: Distance between top and bottom face
    Box depth: Distance between front and back face
    """,
    "Create the printable wraps for both halves of the box "
    "from the template image",
    PLUGIN_AUTHOR,
    PLUGIN_COPYRIGHT,
    PLUGIN_DATE,
    PLUGIN_MENU + "Create wraps from template...",
    "RGB*",
    [
        (gimpfu.PF_IMAGE, "image",
         "Template with six layers",
         0),
        (gimpfu.PF_ADJUSTMENT, "width",
         "Box width [mm]",
         75, (10, 500, 1)),
        (gimpfu.PF_ADJUSTMENT, "height",
         "Box height [mm]",
         104, (10, 500, 1)),
        (gimpfu.PF_ADJUSTMENT, "depth",
         "Box depth [mm]",
         100, (10, 500, 1)),
        (gimpfu.PF_ADJUSTMENT, "thickness",
         "Cardboard thickness [mm]",
         2.0, (0.5, 6.0, 0.5)),
        (gimpfu.PF_ADJUSTMENT, "flap_size",
         "Width of the flaps [mm]",
         10.0, (1.0, 20.0, 1.0)),
        (gimpfu.PF_ADJUSTMENT, "inside_size",
         "Amount of paper inside the box [mm]",
         15.0, (1.0, 50.0, 1.0)),
        (gimpfu.PF_ADJUSTMENT, "crop_mark_size",
         "Size of the crop marks [mm]",
         5.0, (1.0, 20.0, 1.0)),
        (gimpfu.PF_ADJUSTMENT, "crop_mark_distance",
         "Distance between the crop marks and the image [mm]",
         2.0, (0.0, 10.0, 1.0))
    ],
    [],
    create_wraps
)

gimpfu.main()
